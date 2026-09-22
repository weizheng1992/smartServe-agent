"""data agent 轻图(15-D1 单轮小图;阶段④):intake → resolve → [clarify | compile → execute] → 卡片。

刻意不接 StepExecutionEngine/审批引擎/planner 快轨(15 号决议);零 HITL;
SSE 由 gateway 侧路由承载,本模块产出结构化轮次结果。
PageContext(19-D3):route/selection/activeFilters 随问题上星,选中实体
进 intent.entity_ids(IN 绑定,阶段②模板已留位)。
T3 多轮会话(wayfinder dynamic-analytics):session_id → 会话记忆(Redis);
追问在 L0/L2 均未命中后由 LLM 改写为独立问句再走管线,管线本体保持无状态。
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from . import session_store
from .engine import MetricQueryEngine, StructuredQueryIntent, UnsupportedQuery

# 行内商品提及适用闭集(标准商品族:输出商品级榜/单行,模板支持 spu 过滤);
# 时间序列/会话/活动族不在其列 —— 闭集外指标绝不静默扩展绑定语义。
_INLINE_SPU_METRICS = frozenset({"gmv", "volume", "gross_profit", "margin_rate", "stock_risk"})

# 纯图表切换追问(确定性快捷路):问句只含图型词 → 上一轮问句 + 图型要求重解析
_CHART_ONLY_RE = re.compile(r"^(?:换成?|改[成为]?|用|来)?\s*(?:一?个?)?\s*(折线图?|柱状图?|条形图?|柱形图?|表格)\s*[?？]?$")


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

    # 租户必填(2026-09-20 review):静默缺省 "aurora" 会让他租查询冒充 aurora
    # 执行 —— 调用方(gateway SSE/测试)必须显式携带 business_id
    business_id = session_ctx.get("business_id")
    if not business_id:
        raise ValueError("analytics.ask 缺少 business_id:租户隔离不允许静默缺省")
    allowed = await allowed_metrics_for_role(business_id, session_ctx.get("role", "finance_owner"))

    # T3 多轮:pageContext.sessionId → 会话记忆;纯图表切换走确定性快捷路
    session_id = str((page_context or {}).get("sessionId") or "")
    history = await session_store.load(business_id, session_id) if session_id else None
    if history and history.get("last_question"):
        stripped = question.strip()
        if _CHART_ONLY_RE.match(stripped):
            print(f"[Session] 图表切换快捷路: {stripped!r} → 重问 {history['last_question'][:24]!r}")
            question = f"{history['last_question']} {stripped}"

    try:
        intent = engine.resolve(question)
    except UnsupportedQuery:
        # L2 范例回放 → L3 LLM 意图兜底(ADR-0005);全部未命中 → 响亮失败 + 落库
        rewritten_q = None
        try:
            intent, _, rewritten_q = await _fallback_intent(question, allowed, session_ctx, history=history)
        except UnsupportedQuery as err:
            await _log_unanswered(session_ctx, question)
            return {"type": "unsupported", "message": "该问题暂不支持。可试试:销量 Top / 差评榜 / 退款率 / 会话量 / 某活动卖得怎么样 / 某客户最近的订单 / 勾选订单后问「订单对比」", "detail": str(err)}
        if isinstance(intent, dict) and intent.get("clarify"):
            intent.setdefault("originalQuestion", rewritten_q or question)  # 实体反问回问时带上有效问句
            return {"type": "clarify", **_filter_clarify_options(intent, allowed)}
        # 兜底结果同样过角色闭集(防御纵深:resolver 替换/演化时不放行越权)
        if not isinstance(intent, dict) and allowed and intent.metric not in allowed:
            await _log_unanswered(session_ctx, question)
            return {"type": "unsupported", "message": "当前角色无权查看该指标", "detail": intent.metric}
    else:
        rewritten_q = None

    # 改写问句优先:指代已替换成实体名,实体逐字绑定/行内扫描/落存都用它
    effective_question = rewritten_q or question

    if isinstance(intent, dict) and intent.get("clarify"):
        return {"type": "clarify", **_filter_clarify_options(intent, allowed)}

    # 行内商品提及(L0 直出、零 LLM):标准商品族指标的问句逐字包含唯一商品
    # 标题/编码 → 直接绑定 spu 实体槽;零/多命中不改语义(保守放行原问句)。
    # 扫描属可选增强,连接失败降级放行(同 [L2] 范例检索失败先例,主查询仍响亮)。
    if intent.metric in _INLINE_SPU_METRICS and not (intent.entity_slot or {}).get("spu"):
        from . import dimensions

        try:
            mentions = await dimensions.find_inline_spu_mentions(effective_question)
        except Exception as scan_err:
            print(f"[InlineSPU] 行内提及扫描失败(放行原语义): {scan_err}")
            mentions = []
        if len(mentions) == 1:
            intent.entity_slot["spu"] = [mentions[0]["id"]]

    # 必填实体缺失(L0/范例直出):问句里已逐字写明候选名 → 自动绑定;
    # 否则列实体候选反问(entity 类 clarify,帧携带原问题供点选回问)
    missing_kind = _missing_entity_kind(intent)
    if missing_kind:
        from . import dimensions

        candidates = await dimensions.list_candidates(missing_kind)
        # 客户候选 label 是「名 · 手机号」复合串,逐字匹配只看纯名(name 键);
        # 其余种类 name 键缺省回落 label
        mentioned = [
            c for c in candidates
            if (c.get("name") or c["label"]) in effective_question or c["id"] in effective_question
        ]
        if len(mentioned) == 1:
            intent.entity_slot[missing_kind] = [mentioned[0]["id"]]
        else:
            return {
                "type": "clarify",
                "clarifyKind": "entity",
                "question": f"请选择{dimensions.kind_label(missing_kind)}——",
                "originalQuestion": effective_question,
                "options": [{"label": c["label"]} for c in candidates],
            }

    if allowed is not None and intent.metric not in allowed:
        return {
            "type": "unsupported",
            "message": "当前角色无权查看该指标(反问选项集已过滤,此处为直接问越权指标的兜底拒绝)。",
        }

    # 场景包(L2 复合意图):一个意图 = 一组子查询,展开为多帧结果卡
    if intent.metric in _SCENARIO_PACKS:
        outcome = await _run_scenario(intent, session_ctx)
        if session_id:
            await session_store.save(business_id, session_id, {
                "last_question": effective_question, "intent": intent.__dict__,
            })
        return outcome

    # PageContext(19-D3):选中实体作为实体过滤(IN 绑定;长度上限 100)。
    # entity_slot 必须随行保留 —— 勾选重建曾把已绑定的客户/活动/商品槽清空,
    # 实体必传指标(消费统计/优惠券等)被静默绑成空列表 → 假「诚实空」(实弹踩过)。
    selection = (page_context or {}).get("selection") or []
    if selection:
        intent = StructuredQueryIntent(
            metric=intent.metric, direction=intent.direction, limit=intent.limit,
            time_window=intent.time_window, category=intent.category,
            entity_ids=[str(s) for s in selection][:100],
            entity_slot=dict(intent.entity_slot),
            chart_hint=intent.chart_hint,
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

    if session_id:
        # 只存问句与意图,不存结果(数据现查);unsupported/error 不污染历史
        await session_store.save(business_id, session_id, {
            "last_question": effective_question, "intent": intent.__dict__,
        })
    return _result_frame(effective_question, result, intent)


def _result_frame(question: str, result, intent) -> dict:
    cards = build_cards(question, result, intent)
    return {
        "type": "result",
        "metric": result.metric,
        "unit": result.unit,
        "caliber": result.caliber,
        # 用户图表指令(chart_hint)优先,缺省由指标语义自动推断(趋势→折线)
        "chart": intent.chart_hint or result.chart,
        "rows": result.rows,
        "cards": cards,
    }


# 场景包展开表(L2 复合意图,grill 设计定稿):键 = 场景意图,值 = 子指标序列;
# 子指标继承场景意图的实体槽/时间窗/品类。全部走闭集模板,零 LLM。
_SCENARIO_PACKS: dict[str, list[str]] = {
    "biz_overview": ["gmv", "order_count", "aov", "session_volume", "refund_rate"],
    "customer_panorama": ["customer_profile", "customer_coupons", "customer_orders"],
}


async def _run_scenario(intent: StructuredQueryIntent, session_ctx: dict) -> dict:
    """场景包 → 多帧结果卡;每节独立口径注记、独立可导出/存报告。

    某节失败不影响整包:该节以 error 帧如实呈现(诚实原则,不吞不编)。
    """
    engine = MetricQueryEngine(session_ctx=session_ctx)
    frames: list[dict] = []
    for sub_metric in _SCENARIO_PACKS[intent.metric]:
        sub = StructuredQueryIntent(
            metric=sub_metric, direction=intent.direction, limit=intent.limit,
            time_window=intent.time_window, category=intent.category,
            entity_slot=dict(intent.entity_slot),
            chart_hint=intent.chart_hint,
        )
        label = sub_metric
        try:
            compiled = engine.compile(sub)
            result = await engine.execute_async(compiled)
            frames.append(_result_frame(label, result, sub))
        except UnsupportedQuery as err:
            frames.append({"type": "unsupported", "message": str(err), "detail": sub_metric})
        except Exception as err:
            frames.append({"type": "error", "message": f"{sub_metric} 执行失败(已如实报告)", "detail": str(err)})
    return {"type": "multi", "frames": frames}


async def ask_all(question: str, session_ctx: dict, page_context: dict | None = None) -> dict:
    """多轮复合入口:问号显式切分 → 各段独立走完整管线(诚实多卡)。

    单段时行为与 ask() 完全一致;切分只认 ?/?(确定性标点),「和/顺便」等
    软连接词不切 —— 那是 L3 自由分解的职责,规则抢跑会制造错误回答。
    """
    import re as _re

    parts = [p.strip() for p in _re.split(r"[??]", question or "") if p.strip()]
    if len(parts) <= 1:
        return await ask(question, session_ctx, page_context)
    frames: list[dict] = []
    for part in parts:
        try:
            frames.append(await ask(part, session_ctx, page_context))
        except Exception as err:
            frames.append({"type": "error", "message": f"「{part}」执行失败(已如实报告)", "detail": str(err)})
    return {"type": "multi", "frames": frames}


async def _rewrite_followup(question: str, history: dict) -> str | None:
    """LLM 追问改写(Q4b):把依赖上下文的追问改写成独立完整问句。

    仅在 L0/L2 均未命中且会话有历史时触发;失败/未变化 → None,原问句继续
    走 L3(失败依旧响亮)。改写器只产出「问题文本」,绝不产出 SQL —— 08-D1。
    """
    import json as _json

    from .llm_intent import _content_text, get_chat_model

    intent = history.get("intent") or {}
    system = (
        "你是商户数据问答的追问改写器。把依赖上下文的追问改写成独立完整的问题。规则:\n"
        "- 只输出改写后的问题本身,不要任何解释或前缀\n"
        "- 「他/她/它/该客户/这款」等指代 → 用已确认实体名替换\n"
        "- 「换成柱状图/用折线/表格」类 → 在上一轮问题上追加图型要求\n"
        "- 追问与商户数据无关或无法改写 → 原样输出追问\n"
    )
    user = (
        f"上一轮问题:{history.get('last_question', '')}\n"
        f"已确认意图与实体:{_json.dumps(intent, ensure_ascii=False)}\n"
        f"本轮追问:{question}"
    )
    try:
        resp = await get_chat_model().ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=user),
        ])
        out = _content_text(resp).strip()
        return out or None
    except Exception as err:
        print(f"[Session] 追问改写失败(放行原问句): {err}")
        return None


async def _fallback_intent(question: str, allowed: list[str] | None, session_ctx: dict, history: dict | None = None):
    """返回 (intent | clarify dict, via_llm, rewritten):rewritten = 改写后的独立
    问句,外层实体逐字绑定/会话落存必须使用它(原问句是指代,绑不上实体)。"""
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

                return await llm_resolve(question, allowed, session_ctx.get("business_id") or ""), True, None
            print(f"[L2] 范例命中({exemplar['similarity']:.2f}): {exemplar['question'][:40]!r}")
            return StructuredQueryIntent(**exemplar["intent"]), False, None
    except Exception as err:
        print(f"[L2] 范例检索失败(放行 L3): {err}")

    from .llm_intent import _EntityClarify, dimensions, llm_resolve

    # T3 追问改写:L0/L2 均未命中且有会话历史 → LLM 把追问改写成独立问句,
    # 先按改写问句重跑 L0(命中即免费),仍不中则用改写问句继续 L3;
    # rewritten 必须回传外层 —— 实体逐字绑定/会话落存都基于独立完整问句
    rewritten = None
    rewritten_used = False
    if history:
        rewritten = await _rewrite_followup(question, history)
        if rewritten and rewritten != question:
            print(f"[Session] 追问改写: {question[:20]!r} → {rewritten[:30]!r}")
            try:
                hit = MetricQueryEngine(session_ctx=session_ctx).resolve(rewritten)
                if isinstance(hit, StructuredQueryIntent):
                    return hit, False, rewritten
            except UnsupportedQuery:
                pass
            question = rewritten
            rewritten_used = True

    try:
        intent = await llm_resolve(question, allowed, session_ctx.get("business_id") or "")
    except _EntityClarify as entity_clarify:
        print(f"[L3] 实体反问({entity_clarify.kind}): {len(entity_clarify.candidates)} 候选")
        return {
            "clarify": True,
            "clarifyKind": "entity",
            "question": f"请选择{dimensions.kind_label(entity_clarify.kind)}——",
            "options": [{"label": c["label"]} for c in entity_clarify.candidates],
        }, False, None
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
        return intent, True, (rewritten if rewritten_used else None)
    return intent, False, (rewritten if rewritten_used else None)


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
