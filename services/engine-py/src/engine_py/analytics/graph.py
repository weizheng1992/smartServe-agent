"""data agent 轻图(15-D1 单轮小图;阶段④):intake → resolve → [clarify | compile → execute] → 卡片。

刻意不接 StepExecutionEngine/审批引擎/planner 快轨(15 号决议);零 HITL;
SSE 由 gateway 侧路由承载,本模块产出结构化轮次结果。
PageContext(19-D3):route/selection/activeFilters 随问题上星,选中实体
进 intent.entity_ids(IN 绑定,阶段②模板已留位)。
"""

from __future__ import annotations

from typing import Any

from .engine import MetricQueryEngine, StructuredQueryIntent, UnsupportedQuery


def build_cards(question: str, result: Any, intent: StructuredQueryIntent | None = None) -> list[dict]:
    """QueryResult → 卡片(表格为主基座;指标元数据+口径注记必带 —— 诚实呈现)。"""
    if not result.rows:
        return [{
            "type": "text",
            "text": f"「{question}」在当前数据下没有匹配结果(诚实空,非错误)。",
            "caliber": result.caliber,
        }]
    rows = result.rows[: intent.limit if intent else len(result.rows)]
    columns = [{"key": k, "label": k} for k in rows[0]]
    return [{
        "type": "table",
        "title": f"{result.metric} · {result.unit}",
        "columns": columns,
        "rows": [{k: (float(v) if isinstance(v, (int, float)) else str(v)) for k, v in r.items()} for r in rows],
        "caliber": result.caliber,
    }]


async def ask(question: str, session_ctx: dict, page_context: dict | None = None) -> dict:
    """一轮问答:intake(含 PageContext)→ resolve → clarify|execute → 卡片。

    返回 {type: clarify|result|unsupported|error, ...}(gateway SSE 直接序列化)。
    """
    engine = MetricQueryEngine(session_ctx=session_ctx)
    from .rbac import allowed_metrics_for_role

    allowed = await allowed_metrics_for_role(session_ctx.get("role", "finance_owner"))
    try:
        intent = engine.resolve(question)
    except UnsupportedQuery:
        # L2 范例回放 → L3 LLM 意图兜底(ADR-0005);全部未命中 → 响亮失败 + 落库
        try:
            intent, _ = await _fallback_intent(question, allowed, session_ctx)
        except UnsupportedQuery as err:
            await _log_unanswered(session_ctx, question)
            return {"type": "unsupported", "message": "该问题暂不支持。可试试:销量 Top / 差评榜 / 退款率 / 会话量 / 某活动卖得怎么样 / 某客户最近的订单 / 勾选订单后问「订单对比」", "detail": str(err)}
        if isinstance(intent, dict) and intent.get("clarify"):
            intent.setdefault("originalQuestion", question)  # 实体反问回问时带上原问题
            return {"type": "clarify", **_filter_clarify_options(intent, allowed)}
        # 兜底结果同样过角色闭集(防御纵深:resolver 替换/演化时不放行越权)
        if not isinstance(intent, dict) and allowed and intent.metric not in allowed:
            await _log_unanswered(session_ctx, question)
            return {"type": "unsupported", "message": "当前角色无权查看该指标", "detail": intent.metric}

    if isinstance(intent, dict) and intent.get("clarify"):
        return {"type": "clarify", **_filter_clarify_options(intent, allowed)}

    # 必填实体缺失(L0/范例直出):问句里已逐字写明候选名 → 自动绑定;
    # 否则列实体候选反问(entity 类 clarify,帧携带原问题供点选回问)
    missing_kind = _missing_entity_kind(intent)
    if missing_kind:
        from . import dimensions

        candidates = await dimensions.list_candidates(missing_kind)
        mentioned = [c for c in candidates if c["label"] in question or c["id"] in question]
        if len(mentioned) == 1:
            intent.entity_slot[missing_kind] = [mentioned[0]["id"]]
        else:
            return {
                "type": "clarify",
                "clarifyKind": "entity",
                "question": f"请选择{dimensions.kind_label(missing_kind)}——",
                "originalQuestion": question,
                "options": [{"label": c["label"]} for c in candidates],
            }

    if allowed is not None and intent.metric not in allowed:
        return {
            "type": "unsupported",
            "message": "当前角色无权查看该指标(反问选项集已过滤,此处为直接问越权指标的兜底拒绝)。",
        }

    # PageContext(19-D3):选中实体作为实体过滤(IN 绑定;长度上限 100)
    selection = (page_context or {}).get("selection") or []
    if selection:
        intent = StructuredQueryIntent(
            metric=intent.metric, direction=intent.direction, limit=intent.limit,
            time_window=intent.time_window, category=intent.category,
            entity_ids=[str(s) for s in selection][:100],
        )

    try:
        compiled = engine.compile(intent)
        result = await engine.execute_async(compiled)
    except UnsupportedQuery as err:
        # 编译期实体闸(如「未勾选订单」)→ 诚实 unsupported 帧并给出动作提示
        message = str(err) if "勾选" in str(err) else "该指标暂未开放"
        return {"type": "unsupported", "message": message, "detail": str(err)}
    except Exception as err:
        return {"type": "error", "message": "查询执行失败(已如实报告,未生成估算数据)", "detail": str(err)}

    cards = build_cards(question, result, intent)
    return {
        "type": "result",
        "metric": result.metric,
        "unit": result.unit,
        "caliber": result.caliber,
        "chart": result.chart,
        "rows": result.rows,
        "cards": cards,
    }


async def _fallback_intent(question: str, allowed: list[str] | None, session_ctx: dict):
    """L0 未命中后的两级兜底:先 L2 范例回放(近零成本),再 L3 LLM 意图(ADR-0005)。

    返回 (intent | clarify dict, via_llm);全部未命中 → UnsupportedQuery。
    """
    from . import dimensions, exemplar_service

    try:
        exemplar = await exemplar_service.search_exemplar(question, session_ctx.get("business_id") or "")
        if exemplar and exemplar["intent"].get("metric"):
            # 陈旧校验(ADR-0005 后续①):实体槽引用已删除实体 → 停用范例,落 L3
            stale = False
            for kind, ids in (exemplar["intent"].get("entity_slot") or {}).items():
                if ids and not await dimensions.entity_ids_exist(kind, ids):
                    print(f"[L2] 范例陈旧(实体已删,{kind}): 停用并落 L3")
                    await exemplar_service.deactivate_exemplar(exemplar["id"])
                    stale = True
                    break
            if stale:
                from .llm_intent import llm_resolve

                return await llm_resolve(question, allowed, session_ctx.get("business_id") or ""), True
            print(f"[L2] 范例命中({exemplar['similarity']:.2f}): {exemplar['question'][:40]!r}")
            return StructuredQueryIntent(**exemplar["intent"]), False
    except Exception as err:
        print(f"[L2] 范例检索失败(放行 L3): {err}")

    from .llm_intent import _EntityClarify, dimensions, llm_resolve

    try:
        intent = await llm_resolve(question, allowed, session_ctx.get("business_id") or "")
    except _EntityClarify as entity_clarify:
        print(f"[L3] 实体反问({entity_clarify.kind}): {len(entity_clarify.candidates)} 候选")
        return {
            "clarify": True,
            "clarifyKind": "entity",
            "question": f"请选择{dimensions.kind_label(entity_clarify.kind)}——",
            "options": [{"label": c["label"]} for c in entity_clarify.candidates],
        }, False
    if isinstance(intent, StructuredQueryIntent):
        try:
            await exemplar_service.add_exemplar(
                session_ctx.get("business_id") or "__global__",
                question,
                {
                    "metric": intent.metric, "direction": intent.direction, "limit": intent.limit,
                    "time_window": intent.time_window, "category": intent.category,
                    "entity_slot": intent.entity_slot,
                },
                source="llm",
            )
        except Exception as err:
            print(f"[L2] 范例沉淀失败(不影响回答): {err}")
        return intent, True
    return intent, False


def _missing_entity_kind(intent) -> str | None:
    """新族必填实体缺失(经 L0 词表/范例直出、未经实体解析)→ 反问实体。"""
    from .llm_intent import ENTITY_REQUIRED

    if isinstance(intent, dict):
        return None
    kind = ENTITY_REQUIRED.get(intent.metric)
    if kind and not (intent.entity_slot or {}).get(kind):
        return kind
    return None


def _filter_clarify_options(clarify: dict, allowed: list[str] | None) -> dict:
    """反问选项按角色指标闭集过滤(13 号票;实体类选项无 key,不过滤)。"""
    options = clarify.get("options") or []
    if allowed is not None and options and all("key" in o for o in options):
        clarify["options"] = [o for o in options if o.get("key") in allowed]
    return clarify


async def _log_unanswered(session_ctx: dict, question: str) -> None:
    """未命中问句落库(ADR-0005 增长飞轮输入口;失败打印不阻断)。"""
    try:
        from ..db import AgentUnanswered, get_session

        async with get_session() as session:
            session.add(AgentUnanswered(
                business_id=session_ctx.get("business_id") or "aurora",
                role=session_ctx.get("role") or "finance_owner",
                question=question,
            ))
            await session.commit()
    except Exception as err:
        print(f"[Unanswered] 落库失败(放行): {err}")
