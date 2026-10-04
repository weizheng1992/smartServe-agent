"""data agent 轻图(15-D1 单轮小图;阶段④):intake → resolve → [clarify | compile → execute] → 卡片。

刻意不接 StepExecutionEngine/审批引擎/planner 快轨(15 号决议);零 HITL;
SSE 由 gateway 侧路由承载,本模块产出结构化轮次结果。
PageContext(19-D3):route/selection/activeFilters 随问题上星,选中实体
进 intent.entity_ids(IN 绑定,阶段②模板已留位)。
T3 多轮会话(wayfinder dynamic-analytics):session_id → 会话记忆(Redis);
追问在 L0/L2 均未命中后由 LLM 改写为独立问句再走管线,管线本体保持无状态。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace as _dc_replace
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from . import chart_policy, session_store
from .context_intake import INLINE_SPU_METRICS as _INLINE_SPU_METRICS
from .context_intake import (
    inline_order_ids,
    merge_into_intent,
    parse_raw_selection,
)
from .context_intake import (
    title_prefix as build_title_prefix,
)
from .engine import (
    Clarify,
    EntityGateRequired,
    MetricQueryEngine,
    StructuredQueryIntent,
    UnsupportedQuery,
)
from .quick_summary import quick_summary as _quick_summary
from .trace import Trace

# 纯图表切换追问(确定性快捷路):问句只含图型词 → 上一轮问句 + 图型要求重解析
_CHART_ONLY_RE = re.compile(r"^(?:换成?|改[成为]?|用|来)?\s*(?:一?个?)?\s*(折线图?|柱状图?|条形图?|柱形图?|表格)\s*[?？]?$")

# 注入形状闸(2026-10-01 夜审):语料携带 SQL 写关键词串联 / UNION SELECT /
# 指令覆盖语等注入形状时,先于 L0/L2/L3 全部分层确定性拒绝。实证:此类语料
# 会被 L0 词面命中照常出 result 帧(「'; DROP TABLE users; -- 销量排行」命中
# volume、「销售额最高的商品; DELETE FROM orders」命中 gmv),违反「注入语料
# 绝不出 result」安全不变量。合法数据问句不携带这些形状(中文数据问句不含
# 「; 写关键词」/「UNION SELECT」/指令覆盖语);闭集模板 + 绑定参数 + 只读
# 事务仍是数据面唯一出口,此闸属呈现层诚实纪律,不承担数据面安全职责。
_INJECTION_SHAPE_RE = re.compile(
    r";\s*(?:drop|delete|insert|update|alter|truncate)\b"
    r"|\bunion\s+select\b"
    r"|忽略(?:之前|先前|以上|前面)?(?:的)?(?:所有)?指令"
    r"|\bignore\s+previous\s+instructions?\b",
    re.IGNORECASE,
)


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


async def ask(
    question: str, session_ctx: dict, page_context: dict | None = None, *, persist_session: bool = True
) -> dict:
    """一轮问答:intake(含 PageContext)→ resolve → clarify|execute → 卡片。

    返回 {type: clarify|result|unsupported|error, ...}(gateway SSE 直接序列化)。
    persist_session=False 供 ask_all 并发段禁用逐段直接落账(避免完成序竞写):
    save-worthy 载荷改随帧以 `_sessionPayload` 带回,由 ask_all 按输入序单点收口。
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

    trace = Trace(business_id, session_ctx.get("role", "finance_owner"), question)
    if history:
        trace.add_layer("session", followed_up=True)

    # 注入形状闸(先于 L0/L2/L3 全部分层,见 _INJECTION_SHAPE_RE 注):
    # 响亮拒绝 + 落库,注入语料的裁决绝不交给词面命中或兜底 LLM
    if _INJECTION_SHAPE_RE.search(question):
        await _log_unanswered(session_ctx, question)
        await trace.record("unsupported", final_method="injection_guard")
        return {"type": "unsupported", "message": "该问题暂不支持。可试试:销量 Top / 差评榜 / 退款率 / 会话量 / 某活动卖得怎么样 / 某客户最近的订单 / 勾选订单后问「订单对比」", "detail": "问句含注入形状,已拒绝处理"}

    try:
        # resolve 内含分类头同步 torch 推理(shadow/on 灰度期每次必打分,首次还
        # 要加载模型权重),直调会阻塞事件循环 —— 与 llm_intent._sft_generate
        # 同纪律,下放线程执行。
        intent = await asyncio.to_thread(engine.resolve, question)
        trace.add_layer("L0", metric=intent.metric if isinstance(intent, StructuredQueryIntent) else "clarify")
    except UnsupportedQuery:
        # L2 范例回放 → L3 LLM 意图兜底(ADR-0005);全部未命中 → 响亮失败 + 落库
        rewritten_q = None
        try:
            intent, _, rewritten_q = await fallback_intent(question, allowed, session_ctx, history=history, trace=trace)
        except UnsupportedQuery as err:
            await _log_unanswered(session_ctx, question)
            await trace.record("unsupported", final_method="none")
            return {"type": "unsupported", "message": "该问题暂不支持。可试试:销量 Top / 差评榜 / 退款率 / 会话量 / 某活动卖得怎么样 / 某客户最近的订单 / 勾选订单后问「订单对比」", "detail": str(err)}
        if isinstance(intent, Clarify):
            if intent.original_question is None:
                intent = _dc_replace(intent, original_question=rewritten_q or question)  # 实体反问回问时带上有效问句
            await trace.record("clarify")
            return _clarify_frame(intent, allowed)
        # 兜底结果同样过角色闭集(防御纵深:resolver 替换/演化时不放行越权)
        if isinstance(intent, StructuredQueryIntent) and allowed and intent.metric not in allowed:
            await _log_unanswered(session_ctx, question)
            return {"type": "unsupported", "message": "当前角色无权查看该指标", "detail": intent.metric}
    else:
        rewritten_q = None

    # 改写问句优先:指代已替换成实体名,实体逐字绑定/行内扫描/落存都用它
    effective_question = rewritten_q or question

    if isinstance(intent, Clarify):
        await trace.record("clarify")
        return _clarify_frame(intent, allowed)

    # 勾选/订单号/标题前缀 intake(context_intake 单一职责模块)
    sel_orders, sel_spu, sel_cust = parse_raw_selection((page_context or {}).get("selection"))
    if intent.metric == "order_overview" and not intent.entity_ids and not sel_orders:
        sel_orders = inline_order_ids(effective_question)
    intent = merge_into_intent(intent, sel_orders, sel_spu, sel_cust)
    title_prefix = build_title_prefix(
        intent, sel_spu, sel_cust, (page_context or {}).get("selectionLabels") or {},
    )

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
        # 逐字消歧唯一绑定(dimensions.bind_literal 单点,2026-10-03 收口):
        # 客户候选 label 是「名 · 手机号」复合串,纯名 name 键优先
        hit = dimensions.bind_literal(effective_question, candidates, fields=("name", "label", "id"))
        if hit is not None:
            intent.entity_slot[missing_kind] = [hit["id"]]
        else:
            return Clarify(
                kind="entity",
                question=f"请选择{dimensions.kind_label(missing_kind)}——",
                options=[{"label": c["label"]} for c in candidates],
                original_question=effective_question,
            ).to_frame()

    if allowed is not None and intent.metric not in allowed:
        await trace.record("unsupported", final_metric=intent.metric)
        return {
            "type": "unsupported",
            "message": "当前角色无权查看该指标(反问选项集已过滤,此处为直接问越权指标的兜底拒绝)。",
        }

    # 场景包(L2 复合意图):一个意图 = 一组子查询,展开为多帧结果卡
    if intent.metric in _SCENARIO_PACKS:
        outcome = await _run_scenario(intent, session_ctx)
        await trace.record(outcome.get("type", "error"), final_metric=intent.metric,
                           final_method="scenario", row_count=len(outcome.get("frames") or []))
        payload = {"last_question": effective_question, "intent": intent.__dict__}
        if session_id:
            if persist_session:
                await session_store.save(business_id, session_id, payload)
            else:
                outcome["_sessionPayload"] = payload  # 并发段:载荷随帧带回,ask_all 收口
        return outcome

    try:
        compiled = engine.compile(intent)
        result = await engine.execute_async(compiled)
    except UnsupportedQuery as err:
        # 编译期实体闸(EntityGateRequired,「补一句话即可继续」)→ hint 原文
        # 透传;真不支持才替换 generic 文案。2026-10-03 类型化前靠嗅探消息词面
        # (「勾选」)分流,另外四处可行动引导被吞成「该指标暂未开放」。
        message = err.hint if isinstance(err, EntityGateRequired) else "该指标暂未开放"
        await trace.record("unsupported", final_metric=intent.metric)
        return {"type": "unsupported", "message": message, "detail": str(err)}
    except Exception as err:
        await trace.record("error", final_metric=intent.metric)
        return {"type": "error", "message": "查询执行失败(已如实报告,未生成估算数据)", "detail": str(err)}

    outcome = _result_frame(effective_question, result, intent, title_prefix)
    # 缓存命中是机器语义,读字段不解析展示串(口径注记的「缓存读」词面只给人看)
    cache_hit = result.from_cache
    await trace.record(
        outcome.get("type", "error"), final_metric=intent.metric,
        final_method="cache" if cache_hit else "template",
        sql_template=intent.metric, row_count=len(result.rows or []),
        cache_hit=cache_hit,
    )
    # 只存问句与意图,不存结果(数据现查);unsupported/error 不污染历史
    if session_id:
        payload = {"last_question": effective_question, "intent": intent.__dict__}
        if persist_session:
            await session_store.save(business_id, session_id, payload)
        else:
            outcome["_sessionPayload"] = payload  # 并发段:载荷随帧带回,ask_all 收口
    return outcome


def _result_frame(question: str, result, intent, title_prefix: str = "") -> dict:
    from .tools_registry_bridge import metric_semantic_registry

    cards = build_cards(question, result, intent)
    label = metric_semantic_registry().get(intent.metric, {}).get("label") or intent.metric
    title = f"{title_prefix} · {label} · {result.unit}" if title_prefix else f"{label} · {result.unit}"
    return {
        "type": "result",
        "title": title,
        "metric": result.metric,
        "unit": result.unit,
        "caliber": result.caliber,
        # 用户图表指令(chart_hint)优先,缺省由指标语义自动推断(趋势→折线);
        # 仲裁唯一出处 chart_policy.decide(2026-10-03 收口)
        "chart": chart_policy.decide(intent.chart_hint, intent.metric, result.chart),
        "summary": _quick_summary(result, intent),
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

    async def _one(sub_metric: str) -> dict:
        sub = StructuredQueryIntent(
            metric=sub_metric, direction=intent.direction, limit=intent.limit,
            time_window=intent.time_window, category=intent.category,
            entity_slot=dict(intent.entity_slot),
            chart_hint=intent.chart_hint,
        )
        try:
            result = await engine.execute_async(engine.compile(sub))
            return _result_frame(sub_metric, result, sub)
        except UnsupportedQuery as err:
            return {"type": "unsupported", "message": str(err), "detail": sub_metric}
        except Exception as err:
            return {"type": "error", "message": f"{sub_metric} 执行失败(已如实报告)", "detail": str(err)}

    # 各节互不依赖,execute_async 每次自开独立会话/连接 —— 并发执行省整包时延;
    # gather 保序(frames 顺序仍 = pack 顺序),单节失败照旧不炸整包(夜审 2026-09-29)
    frames = list(await asyncio.gather(*(_one(m) for m in _SCENARIO_PACKS[intent.metric])))
    return {"type": "multi", "frames": frames}


async def ask_all(question: str, session_ctx: dict, page_context: dict | None = None) -> dict:
    """多轮复合入口:问号显式切分 → 各段独立走完整管线(诚实多卡)。

    单段时行为与 ask() 完全一致;切分只认 ?/?(确定性标点),「和/顺便」等
    软连接词不切 —— 那是 L3 自由分解的职责,规则抢跑会制造错误回答。

    各段互不依赖(execute_async 每次自开独立会话/连接),gather 并发省整包
    时延(2026-10-02 夜审:逐段 await 是 N 段时延之和)。会话收口:各段以
    persist_session=False 执行、载荷随帧带回,此处按**输入序**取最后一个
    save-worthy 段单点落账 —— 与串行版「逐段 save、后段覆盖前段」的最终态
    一致(末段 unsupported/error 时保留前一个成功段的历史),且与完成序无关。
    """
    parts = [p.strip() for p in re.split(r"[??]", question or "") if p.strip()]
    if len(parts) <= 1:
        return await ask(question, session_ctx, page_context)

    async def _one(part: str) -> dict:
        try:
            return await ask(part, session_ctx, page_context, persist_session=False)
        except Exception as err:
            return {"type": "error", "message": f"「{part}」执行失败(已如实报告)", "detail": str(err)}

    frames = list(await asyncio.gather(*(_one(part) for part in parts)))

    session_id = str((page_context or {}).get("sessionId") or "")
    if session_id:
        last_payload = None
        for frame in frames:  # 弹走私键(不入 SSE 线格式),输入序取最后 save-worthy
            payload = frame.pop("_sessionPayload", None)
            if payload is not None:
                last_payload = payload
        if last_payload is not None:
            await session_store.save(session_ctx["business_id"], session_id, last_payload)
    else:
        for frame in frames:
            frame.pop("_sessionPayload", None)
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


async def fallback_intent(question: str, allowed: list[str] | None, session_ctx: dict, history: dict | None = None, trace: Trace | None = None):
    """L0 未命中后的两级兜底(公共面:测试/工具经此注入或观察 L2/L3 阶梯):
    先 L2 范例回放(近零成本),再 L3 LLM 意图(ADR-0005)。

    返回 (StructuredQueryIntent | Clarify, via_llm);全部未命中 → UnsupportedQuery。
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
            if trace:
                trace.add_layer("L2", similarity=round(exemplar["similarity"], 3), exemplar=exemplar["question"][:40])
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
            if trace:
                trace.add_layer("rewrite", rewritten=rewritten[:40])
            try:
                hit = await asyncio.to_thread(MetricQueryEngine(session_ctx=session_ctx).resolve, rewritten)
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
        return (
            Clarify(
                kind="entity",
                question=f"请选择{dimensions.kind_label(entity_clarify.kind)}——",
                options=[{"label": c["label"]} for c in entity_clarify.candidates],
            ),
            False,
            None,
        )
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
        if trace:
            trace.add_layer("L3", metric=intent.metric)
        return intent, True, (rewritten if rewritten_used else None)
    return intent, False, (rewritten if rewritten_used else None)


def _missing_entity_kind(intent) -> str | None:
    """新族必填实体缺失(经 L0 词表/范例直出、未经实体解析)→ 反问实体。"""
    from .llm_intent import ENTITY_REQUIRED

    if not isinstance(intent, StructuredQueryIntent):
        return None  # Clarify 等非意图结果无实体槽可言
    kind = ENTITY_REQUIRED.get(intent.metric)
    if kind and not (intent.entity_slot or {}).get(kind):
        return kind
    return None


def _clarify_frame(clarify: Clarify, allowed: list[str] | None) -> dict:
    """反问帧:选项按角色指标闭集过滤(13 号票;实体类选项无 key,不过滤)。"""
    options = clarify.options or []
    if allowed is not None and options and all("key" in o for o in options):
        clarify = _dc_replace(clarify, options=[o for o in options if o.get("key") in allowed])
    return clarify.to_frame()


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
