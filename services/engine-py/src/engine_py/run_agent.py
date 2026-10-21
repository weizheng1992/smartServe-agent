"""run_agent — TS 侧 runAgent()(packages/engine/src/graph/buildGraph.ts)的全量移植。

行为清单(全部已移植):
1. 零 LLM 欢迎语快路径(isQuickGreeting → 10ms 闪电旁路)
2. 租户配置热加载(business_configs 活跃快照;fallback:nike $150 / adidas $120 / 默认 $100)
3. 单 embedding 注入 + 三路并取(LongMemory / EpisodicMemory / ContextualRAG,
   asyncio.gather(return_exceptions=True),任意失败不阻断)
4. session_metrics 遥测写入(成本换算 $0.15/M tokens)
5. LangSmith feedback POST 回传(LANGCHAIN_API_KEY 存在时后台异步)
6. CardSynthesizer 卡片合成
7. 终态 `${jobId}:result` 事件收口发布

收口(Settle,内部缝):4/6/7 及坏例信号入池、订单宣称反幻觉闸、记忆回写、
任务记忆落库,全部内聚在私有缝 `_settle_turn` —— 图后持久化的唯一实现,
顺序即契约(ADR-0007:旧 Temporal activity 手抄的第二份收口已随路线退役,
漂移类 bug 失去存在条件)。

TODO(Phase 1b):token 累计已由 llm/telemetry.py 落盘 llm_call_logs 并聚合
(2026-09-05 起,total_tokens 为本次运行真实 usage 总和);熔断/退避/超时已由
llm/resilience.py 承担(2026-09-07,wayfinder 003)。
"""

from __future__ import annotations

import asyncio
import os
import time

from pydantic import BaseModel, Field
from sqlalchemy import select, text

from .badcase.intent_signals import record_claim_mismatch_if_any
from .badcase.pool import SOURCE_CIRCUIT_BREAKER, record_badcase_signal
from .cards import CardSynthesizer
from .credits import refund_credit
from .db import BusinessConfigRow, SessionMetric, Thread, get_session
from .event_bus import emit_job_result, emit_status, publish_agent_event
from .graph import build_graph
from .graph.build_graph import CIRCUIT_BREAKER_TOOL_ERRORS, CIRCUIT_BREAKER_TRANSITIONS
from .graph.state import DEFAULT_TASK_PLAN, AgentState, to_ts_dict
from .interruption import register_run, run_graph_with_interruption, unregister_run
from .llm import (
    CircuitBreakerOpenError,
    LlmQuotaError,
    bind_llm_call_context,
    drain_llm_call_writes,
    get_embedding_model,
    take_thread_token_total,
)
from .memory import EpisodicMemory, LongMemory, ShortMemory, TaskMemory
from .memory.context_builder import build_history_block, summarize_overflow
from .onboarding import build_entry_cards, resolve_onboarding_config
from .ontology_generated import DEFAULT_REFUND_AUTO_APPROVAL_LIMIT
from .rag import ContextualRAG
from .tenant import get_merchant_display_name
from .tenant_context import set_business_context
from .tools_registry.mall_domain import MallDomainService
from .triage import rule_matchers
from .triage.intent_registry import CONSULT_SIDE_INTENTS
from .triage.rule_matchers import is_quick_greeting
from .vision import normalize_image_urls

# 积分退回白名单(2026-10-21 配额闸 D2):降级道歉族 = 用户只收到道歉、未获得
# 任何真实答案的技术失败;interrupted(用户主动停)/ 子任务 failed(真实处理
# 已发生)/ waiting_approval(HITL 挂起)不退。
_REFUNDABLE_STATUSES = frozenset({
    "llm_circuit_breaker",
    "llm_quota_exhausted",
    "graph_error_degraded",
    "circuit_breaker",
})


class AgentJobInput(BaseModel):
    """作业输入 — 字段与 WorkflowOrchestrator.dispatchJob 的载荷对齐。"""

    job_id: str = Field(alias="jobId")
    thread_id: str = Field(alias="threadId")
    user_id: str = Field(default="CUST-8801", alias="userId")
    business_id: str = Field(default="ecommerce", alias="businessId")
    message: str
    image_urls: list[str] = Field(default_factory=list, alias="imageUrls")
    # 商户门户商城车条目(2026-09-14 空车谎报收口):门户加购只写浏览器
    # localStorage,引擎车在 Redis 两存储互不相通 —— 携带即水合,见
    # MallDomainService.hydrate_cart_from_storefront
    store_cart: list[dict] = Field(default_factory=list, alias="storeCart")

    model_config = {"populate_by_name": True}


async def _ensure_thread(thread_id: str, user_id: str, business_id: str | None) -> None:
    """多租户外键一致性保障:确保物理 threads 行在 messages 写入前已落盘。

    ON CONFLICT 只续租 updated_at,绝不覆盖已有线程的 business_id ——
    线程的租户归属在其创建时即冻结(架构不变量 #1),防止缺省派发方
    (如审批恢复未携带 businessId)把线程静默"搬家"到默认租户。
    """
    async with get_session() as session:
        await session.execute(
            text(
                'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                "VALUES (:tid, :uid, :bid, 'active', NOW(), NOW()) "
                'ON CONFLICT (id) DO UPDATE SET "updated_at" = NOW()'
            ).bindparams(tid=thread_id, uid=user_id, bid=business_id or "ecommerce")
        )
        await session.commit()


async def _resolve_business_context(
    thread_id: str, user_id: str, override_business_id: str | None
) -> tuple[str, dict]:
    """租户身份核验 + business_configs 热加载(带回退默认阈值)。"""
    business_id = override_business_id or "ecommerce"
    initial_brand_name = get_merchant_display_name(business_id)
    dynamic_config = {
        "businessId": business_id,
        "systemPrompt": (
            f"You are an advanced, professional AI Customer Support Agent representing {initial_brand_name}. "
            "Help users resolve order, shipping, and refund queries."
        ),
        "intents": {
            "order_status": {"description": "Track or check order delivery status."},
            "refund": {"description": "Process or request refunds."},
            "general_query": {"description": "General customer questions."},
        },
        "tools": ["getOrderStatus", "processRefund", "takeScreenshot", "listUserOrders"],
        "executionMode": "plan-and-execute",
        "confidenceThresholds": {"high": 0.85, "mid": 0.6},
        # 免签缺省单源(ADR-0015 决策 4):六处 50/100 分叉统一 50(收紧方向)
        "refundAutoApprovalLimit": DEFAULT_REFUND_AUTO_APPROVAL_LIMIT,
    }

    try:
        await _ensure_thread(thread_id, user_id, override_business_id)
        async with get_session() as session:
            thread_row = (
                await session.execute(select(Thread).where(Thread.id == thread_id).limit(1))
            ).scalar_one_or_none()
            if thread_row and thread_row.business_id:
                business_id = thread_row.business_id

            config_row = (
                await session.execute(
                    select(BusinessConfigRow)
                    .where(
                        BusinessConfigRow.business_id == business_id,
                        BusinessConfigRow.is_active.is_(True),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()

            if config_row and config_row.config:
                dynamic_config = {**dynamic_config, **config_row.config, "businessId": business_id}
            else:
                # 自愈装配(Nike $150 / Adidas $120 显式覆写;主站随平台缺省
                # —— ADR-0015 决策 4,历史 $100 分叉收口为 50)
                default_limit = (
                    150 if business_id == "nike"
                    else 120 if business_id == "adidas"
                    else DEFAULT_REFUND_AUTO_APPROVAL_LIMIT
                )
                dynamic_config = {**dynamic_config, "businessId": business_id, "refundAutoApprovalLimit": default_limit}
    except Exception as err:
        print(f"[SaaS Config Engine] Failed to dynamically load business config: {err}")

    return business_id, dynamic_config


def _degraded_apology_result(source: str = "graph_error") -> dict:
    """降级结果:道歉回复 + 空计划,沿用图终态消费链路;文案按降级来源分流
    (2026-10-15 夜评台账 #2 —— 「上游模型波动」一词此前混淆 LLM 熔断/余额
    缺额/图执行异常三类来源,三次排障误判,用户所见与遥测同口径)。

    run_agent 主流程(metrics 落盘 / 任务记忆 / result 事件)继续走通;
    resolution_status 由调用方按旗标落 ``llm_circuit_breaker`` /
    ``llm_quota_exhausted`` / ``graph_error_degraded``(区分降级来源,遥测如实)。
    """
    copy_by_source = {
        # 瞬态可用性波动(连续失败熔断):上游模型波动语义贴切
        "llm_circuit_breaker": (
            "非常抱歉,智能服务当前遇到上游模型波动,暂时无法处理您的请求。"
            "请稍后再试,或选择人工客服协助。"
        ),
        # 账户额度缺额(code 1113):缺的是钱不是模型,严禁谎称波动
        "llm_quota": (
            "非常抱歉,智能客服当前因服务额度限制暂时不可用,我们正在紧急处理。"
            "请稍后再试,或选择人工客服协助。"
        ),
        # 图执行异常(重试耗尽/单节点 bug 等):与模型可用性无关
        "graph_error": (
            "非常抱歉,系统处理您的请求时遇到异常,暂时无法完成答复。"
            "请稍后再试,或选择人工客服协助。"
        ),
    }
    return {
        "output": copy_by_source.get(source, copy_by_source["graph_error"]),
        "task_plan": dict(DEFAULT_TASK_PLAN),
        "loop_count": 0,
        "global_transitions_count": 0,
        "tool_errors_count": 0,
    }


_langsmith_client: object | None = None  # httpx.AsyncClient,懒建进程级复用(P11)


def _get_langsmith_client():
    """进程级复用 httpx 客户端(P11,2026-10-03):旧实现每回合
    `async with httpx.AsyncClient()` 新建连接池 + TLS 握手,遥测白付全额;
    httpx 客户端线程安全可跨请求复用,与 llm/chat 的 lru_cache 单例同纪律。"""
    global _langsmith_client
    import httpx

    if _langsmith_client is None or getattr(_langsmith_client, "is_closed", False):
        _langsmith_client = httpx.AsyncClient(timeout=10.0)
    return _langsmith_client


async def _report_langsmith_feedback(is_success: bool, comment: str) -> None:
    """后台 fire-and-forget 上报 LangSmith 语义反馈(TS 侧无 runId 桥接,标记简化)。"""
    api_key = os.environ.get("LANGCHAIN_API_KEY")
    if not api_key:
        return
    endpoint = os.environ.get("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    try:
        client = _get_langsmith_client()
        for key in ("correctness", "success"):
            await client.post(
                f"{endpoint}/feedback",
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "key": key,
                    "score": 1.0 if is_success else 0.0,
                    "value": "success" if is_success else "failure",
                    "comment": comment,
                },
            )
    except Exception as telemetry_err:
        print(f"[LangSmith Telemetry] Error uploading feedback to LangSmith: {telemetry_err}")


async def _settle_turn(
    result: AgentState,
    *,
    job: AgentJobInput,
    business_id: str,
    llm_breaker_fired: bool,
    llm_quota_fired: bool = False,
    graph_error_fired: bool = False,
    elapsed_latency_ms: float,
    saved_guide_context: dict | None,
    saved_cart_context: dict | None,
    saved_order_context: dict | None,
    history_summary_final: str | None = None,
    interrupted: bool = False,
) -> dict:
    """收口(内部缝):图终态 → 交付调用方之间的唯一持久化段,顺序即契约。

    遥测落盘(token 聚合 + session_metrics + 熔断/宣称坏例信号)→ 订单宣称
    反幻觉闸 → 富媒体卡片合成 → 助手回复回写三路记忆 → 任务记忆落库 →
    `${jobId}:result` 事件发布。各段自吞错不阻断交付;返回值即调用方交付的
    final_result。身份实参(business_id 为线程行自愈后的权威租户)由 run_agent
    显式递入 —— 降级臂结果里没有 business_config,收口不得依赖图终态携带租户。

    interrupted(S2c):用户主动中断的运行级收口 —— resolution_status 落
    ``interrupted``(独立值,压倒子任务态:中途停止 ≠ 等待审批/失败);result
    帧仍发布(网关「result 帧优雅收口」语义不变,否则 SSE 流挂死)但带
    ``interrupted: True`` 诚实标注;中断不是缺陷,不入坏例池。
    """
    thread_id = job.thread_id
    user_id = job.user_id
    input_message = job.message
    job_id = job.job_id
    short_memory = ShortMemory(thread_id, 10, business_id)
    task_memory = TaskMemory(thread_id)
    long_memory = LongMemory(user_id, business_id)
    episodic_memory = EpisodicMemory(user_id, business_id)

    # ── P2(2026-10-03):收口四条独立泳道并行(旧实现遥测→坏例→宣称闸→卡片→
    # 记忆→任务记忆全串行 await 链,时延为各段之和)。依赖契约:
    #   · drain→take 在遥测泳道内保持串行(先收口落盘再取真值);
    #   · claim_mismatch 读 pre-guard 原文快照(与旧顺序语义一致,先取快照防
    #     与 sanitize 泳动同字典竞写);
    #   · 记忆回写在 join 之后(必须见 sanitize 后终稿与最终卡片);
    #   · result 事件恒最后(交付信号)。各泳道自吞异常,降级粒度不变。

    output_before_guard = str(result.get("output") or "")

    async def _settle_metrics_lane() -> None:
        """遥测泳道:drain → 真值取数 → 状态判定 → LangSmith 派发 → metrics 落盘 → 熔断坏例入池。"""
        try:
            await drain_llm_call_writes(thread_id)
            total_tokens = take_thread_token_total(thread_id)
            cost_usd = (total_tokens / 1_000_000) * 0.15
            node_transitions = result.get("loop_count") or 3

            # 🛡️ 图级熔断落盘:10 步/3 错触发时 resolution_status = circuit_breaker(终态优先于子任务状态)
            global_transitions = result.get("global_transitions_count") or 0
            tool_errors = result.get("tool_errors_count") or 0
            breaker_fired = (
                global_transitions >= CIRCUIT_BREAKER_TRANSITIONS or tool_errors >= CIRCUIT_BREAKER_TOOL_ERRORS
            )

            # 🛡️ LLM 熔断落盘(resilience.py 全局熔断器拦截):job 级终态,优先于图级判定。
            # 中断旗标列首位:S2c 与两熔断臂按构造互斥(中断走正常流退出,熔断走异常臂),
            # 防御性优先只表达「运行级用户中断是最高叙事优先级」;子任务态(waiting_approval
            # 等)再低一档 —— 中途停止的计划若按 waiting_approval 落,会把「用户已停止」
            # 谎成「等待审批」,污染 HOT-RESUME 恢复面语义。
            if interrupted:
                resolution_status = "interrupted"
                is_success = False
                feedback_comment = "Run interrupted by user before finish."
            elif llm_breaker_fired:
                resolution_status = "llm_circuit_breaker"
                is_success = False
                feedback_comment = "Upstream LLM circuit breaker open; job degraded with apology fallback."
            elif llm_quota_fired:
                # 账户额度缺额独立落盘(2026-10-15 夜评台账 #2):严禁混入
                # llm_circuit_breaker/graph_error —— 排障口径与用户文案同源
                resolution_status = "llm_quota_exhausted"
                is_success = False
                feedback_comment = "Provider account quota exhausted (code 1113); job degraded."
            elif graph_error_fired:
                resolution_status = "graph_error_degraded"
                is_success = False
                feedback_comment = "Graph execution raised; job degraded with apology fallback."
            else:
                resolution_status = "circuit_breaker" if breaker_fired else "resolved_auto"
                is_success = not breaker_fired
                feedback_comment = (
                    "Circuit breaker tripped: hard degradation with apology fallback."
                    if breaker_fired
                    else "All planned subtasks completed successfully."
                )

            plan = result.get("task_plan") or {}
            subtasks = plan.get("subtasks") or []
            # 运行级中断(interrupted)压倒子任务态:运行没跑完,子任务状态不是
            # 终局叙事(中途停止的挂起子任务若按 waiting_approval 落,会把「用户
            # 已停止」谎成「等待审批」)
            if subtasks and not breaker_fired and not interrupted:
                has_pending = any((st.get("result") or {}).get("waitingForApproval") for st in subtasks)
                has_cancelled = any((st.get("result") or {}).get("cancelledByUser") for st in subtasks)
                has_expired = any((st.get("result") or {}).get("expiredByTimeout") for st in subtasks)
                has_rejected = any(
                    st.get("status") == "failed" and (st.get("result") or {}).get("rejectedByAdmin")
                    for st in subtasks
                )
                has_failed = any(st.get("status") == "failed" for st in subtasks)

                if has_pending:
                    resolution_status = "waiting_approval"
                elif has_cancelled:
                    resolution_status = "cancelled"
                elif has_expired:
                    resolution_status = "expired"
                elif has_rejected:
                    resolution_status = "rejected"
                elif has_failed:
                    resolution_status = "failed"
                    is_success = False
                    feedback_comment = "Some planned subtasks failed validation or execution."

            if os.environ.get("LANGCHAIN_API_KEY"):
                asyncio.create_task(_report_langsmith_feedback(is_success, feedback_comment))

            async with get_session() as session:
                session.add(
                    SessionMetric(
                        business_id=business_id,
                        thread_id=thread_id,
                        total_tokens=total_tokens,
                        calculated_cost_usd=cost_usd,
                        node_transitions_count=node_transitions,
                        global_transitions_count=global_transitions,
                        tool_errors_count=tool_errors,
                        resolution_status=resolution_status,
                        avg_latency_ms=elapsed_latency_ms,
                    )
                )
                await session.commit()

            # 积分退回(2026-10-21 配额闸 D2):降级道歉族 = 未产出有效答案的
            # 技术失败(用户只收到道歉,问询积分原路退回;refund 部分唯一索引
            # 挡双退)。用户主动中断(自己的选择)与子任务级 failed(真实处理
            # 已发生,有诚实答复)不退。
            if resolution_status in _REFUNDABLE_STATUSES:
                if await refund_credit(business_id, job_id=job_id):
                    print(f"[Quota] 技术失败退回积分: job={job_id} biz={business_id} status={resolution_status}")

            # 📥 熔断信号入坏例池(wayfinder 006):被熔断打断的会话以会话为评审
            # 单位入池(先验 suspected_defect,人审定性,见 badcase/pool.py)。
            # 挂点定案:收口处而非状态机翻转处 —— 翻转可能发生在无会话归属的
            # 后台调用,而池以会话为评审单位,与 session_metrics 熔断落盘(003
            # 数据源)同位;dedupe=True 使 OPEN 窗口内同一会话多次回合只入池一次;
            # 入池失败静默降级不阻断主流程(内建)。
            if (llm_breaker_fired or llm_quota_fired or graph_error_fired or breaker_fired) and not interrupted:
                # 中断不是缺陷(S2c):用户掐死打转 run 的部分态(tool_errors≥3 /
                # 转移≥22 正是取消的典型形态)不入坏例池 —— 那是产品行为不是缺陷信号
                await record_badcase_signal(
                    SOURCE_CIRCUIT_BREAKER,
                    conversation_ref=f"thread:{thread_id}",
                    business_id=business_id,
                    dedupe=True,
                    note=(
                        "上游 LLM 熔断(OPEN)拦截,会话降级道歉回复"
                        if llm_breaker_fired
                        else (
                            "供应商账户额度缺额(1113),会话降级道歉回复"
                            if llm_quota_fired
                            else (
                                "图执行未捕获异常,降级道歉回复"
                                if graph_error_fired
                                else f"图级熔断:全局转移 {global_transitions} 次 / 工具错误 {tool_errors} 次"
                            )
                        )
                    ),
                )
        except Exception as metrics_err:
            print(f"[SaaS Telemetry] Failed to persist session metrics in physical table: {metrics_err}")

    async def _settle_claim_lane() -> None:
        """宣称不符信号泳道:读 pre-guard 原文快照(与旧串行顺序语义一致)。"""
        try:
            # 🔍 宣称与落库不符信号入池(intent-arbitration 02):终稿宣称已退款/
            # 已提交审批 × 审批表整会话零记录 → 候选行(先验 suspected_defect)。
            # ORD-77777 编造审批一类:幽灵单拦截挡住了开单,终稿幻觉的宣称仍要
            # 能被捕到;入池静默降级不阻断收口。
            await record_claim_mismatch_if_any(thread_id, business_id, output_before_guard)
        except Exception as claim_err:
            print(f"[runAgent] 宣称不符信号入池失败(不阻断): {claim_err!r}")

    async def _settle_guard_lane() -> None:
        """订单宣称反幻觉硬闸泳道:终稿宣称单号必须来自本轮 checkoutCart 真实结果。"""
        try:
            from .graph.nodes.output_guard import sanitize_order_claims

            result["output"] = await sanitize_order_claims(output_before_guard, result.get("task_plan"))
        except Exception as guard_err:
            print(f"[runAgent] 订单宣称校验失败(放行原文,不阻断): {guard_err!r}")

    shelf_task = CardSynthesizer.fetch_shelf_categories(result.get("intents"), thread_id)
    _, _, _, shelf_categories = await asyncio.gather(
        _settle_metrics_lane(),
        _settle_claim_lane(),
        _settle_guard_lane(),
        shelf_task,
    )

    # 🗂️ 富媒体卡片合成(ADR-0001:场景化快捷回复;域卡片优先作基座,
    # 场景组统一追加;购物轮实查真货架品类喂 chips,不可达诚实空)
    final_cards = CardSynthesizer.synthesize_cards(
        {
            "taskPlan": result.get("task_plan"),
            "intents": result.get("intents"),
            "damageAssessment": result.get("damage_assessment"),
            "existingCards": result.get("cards") or [],
            "shelfCategories": shelf_categories,
            "ragDocuments": result.get("rag_documents") or [],
        }
    )

    # 助手回复回写三路记忆 + 任务记忆落库(join 后四路并行;回复已产出,
    # 持久化失败不阻断交付)。各象限独立降级:单路失败只吞本路,严禁连坐——
    # 否则 episodic 抛错会静默跳过 long 事实抽取(2026-10-02 夜审收口)。
    task_plan_to_save = result.get("task_plan") or {
        "goal": "Multi-turn conversational assistance",
        "subtasks": [],
        "currentStepIndex": 0,
    }

    async def _task_memory_lane():
        try:
            await task_memory.save_task_state(
                {
                    **task_plan_to_save,
                    "guideContext": result.get("guide_context") or saved_guide_context,
                    "cartContext": result.get("cart_context") or saved_cart_context,
                    "orderContext": result.get("order_context") or saved_order_context,
                    "historySummary": history_summary_final,
                }
            )
        except Exception as tm_err:
            print(f"[runAgent] 任务状态落库失败(不阻断): {tm_err!r}")

    if result.get("output"):
        async def _short_lane():
            try:
                await short_memory.add_message("assistant", result["output"], final_cards)
            except Exception as mem_err:
                print(f"[runAgent] 短期记忆回写失败(不阻断): {mem_err!r}")

        async def _episodic_lane():
            try:
                # P3(2026-10-03):情境记忆只记业务动作回合 —— 旧实现每回合无条件写
                # 「Handled conversation thread...」样板并白付一次 embedding:既稀释
                # [MEMORY OF PAST EVENTS] 的召回面,又徒增每回合成本。动作形回合
                # (退款/改址/购物车等,以 consult 侧意图补集为口径,复用
                # intent_registry 仲裁同源集合)才入池;纯问答由 long_memory 画像
                # 抽取承载,寒暄走问候旁路本就不到这里。
                _turn_intents = {
                    str(i.get("intent") or "").strip().lower() for i in result.get("intents") or []
                }
                _action_intents = _turn_intents - CONSULT_SIDE_INTENTS - {""}
                if _action_intents or result.get("damage_assessment"):
                    await episodic_memory.add_event(
                        f"Handled conversation thread: {thread_id}. Output summary: {result['output'][:80]}",
                        _episodic_importance(result["output"]),
                    )
            except Exception as mem_err:
                print(f"[runAgent] 情境记忆回写失败(不阻断): {mem_err!r}")

        async def _long_lane():
            try:
                await long_memory.extract_and_store_fact(result["output"], input_message)
            except Exception as mem_err:
                print(f"[runAgent] 长期记忆回写失败(不阻断): {mem_err!r}")

        await asyncio.gather(_short_lane(), _episodic_lane(), _long_lane(), _task_memory_lane())
    else:
        # 无 output(降级/空终稿):任务记忆仍须落库(挂起计划等恢复状态依赖它)
        try:
            await task_memory.save_task_state(
                {
                    **task_plan_to_save,
                    "guideContext": result.get("guide_context") or saved_guide_context,
                    "cartContext": result.get("cart_context") or saved_cart_context,
                    "orderContext": result.get("order_context") or saved_order_context,
                    "historySummary": history_summary_final,
                }
            )
        except Exception as tm_err:
            print(f"[runAgent] 任务状态落库失败(不阻断): {tm_err!r}")

    final_result = {**to_ts_dict(result), "cards": final_cards}
    if interrupted:
        # S2c:result 帧仍发(网关按 result 帧优雅收口,不发则 SSE 流挂死),
        # 但带 interrupted 标记诚实声明「未完成」—— 严禁复用 error 帧或沉默
        final_result["interrupted"] = True

    if job_id:
        try:
            await publish_agent_event(job_id, "result", final_result)
        except Exception as pub_err:
            print(f"[runAgent] 结果事件发布失败(sync 返回值仍完整): {pub_err!r}")

    return final_result


async def _maybe_continue_rewrite(
    job: AgentJobInput,
    input_message: str,
    short_memory: ShortMemory,
    task_memory: TaskMemory,
) -> str:
    """「继续」确定性重派(ADR-0013 决策 2,2026-10-10):上轮 assistant 缺失
    或失败时,把输入改写回上轮用户原问题 —— 不是旁路重放(上轮无可放之物),
    是替用户把没被回答的问题重新问一遍,复用整条既有管线。静默重答,无前缀。

    五道闸,任一不过原样放行;全函数 try/except 包裹(无异常冷启动,闸数据
    不可得一律放行)。改写挂 run_agent 入口而非 triage Stage:StageContext 的
    input/clean_input 是不变组(13 出口/41 处读取共享同一可变事实的只读纪律),
    改写必须在 ctx 构造之前发生 —— 见 .scratch/chat-disconnect-recovery/spec.md
    §2.2 的偏差记录。时序口径:本轮「继续」的 user 行由网关 chat_turn 先行落库,
    故上轮问题 = user_msgs[-2](与 duplicate_intercept 同一口径)。"""
    try:
        # 闸① 整句等值词表(规整后精确匹配;子串会撞 MULTI_INTENT 连接词
        # 「然后|接着」、误劫持「继续推荐便宜的」这类带新诉求的合法输入)
        if not rule_matchers.is_continue_word(input_message):
            return input_message
        # 闸② 带图轮次豁免(图证即新证据,与 duplicate_intercept 同源纪律)
        if job.image_urls:
            return input_message
        # 闸③ 无待决议审批 —— HOT-RESUME 契约:planner 测试正拿裸「继续」
        # 钉「审批未决议必须深规划」。spec 从宽口径:pendingAction 任意真值
        # 即让位;审批数据不可得同样让位(无法排除待决议,保守放行)
        try:
            saved_state = await task_memory.get_task_state()
        except Exception:
            return input_message
        if isinstance(saved_state, dict) and saved_state.get("pendingAction"):
            return input_message
        # 闸④⑤ 上轮有 user 文本,且上一条 assistant 缺失或失败(正常完成时
        # 「继续」交回 LLM 自由发挥——继续推荐更多本来就是对的)
        history = await short_memory.get_messages()
        user_msgs = [m for m in history if m.get("role") == "user"]
        if len(user_msgs) < 2:
            return input_message
        prev_question = str(user_msgs[-2].get("content") or "").strip()
        if not prev_question:
            return input_message
        assistant_msgs = [m for m in history if m.get("role") == "assistant"]
        if assistant_msgs and not rule_matchers.is_failed_response(
            str(assistant_msgs[-1].get("content") or "")
        ):
            return input_message
        print(
            f"[ContinueRewrite] 「继续」重派上轮问题 threadId={job.thread_id} "
            f"rewritten_to={prev_question[:40]!r}"
        )
        return prev_question
    except Exception as err:
        print(f"[ContinueRewrite] 判定异常,原样放行: {err}")
        return input_message


def _episodic_importance(output_text: str) -> int:
    """情境记忆重要性规则打分(2026-09-21 拷问轮决议,替代恒 5):
    资损/履约硬事实(退款/投诉/订单号/运单/金额)权重高,常规动作 5,轻交互 4。"""
    text = output_text or ""
    if any(k in text for k in ("退款", "退货", "投诉", "赔付", "赔偿")):
        return 9
    if "ORD-" in text or "订单号" in text or "金额" in text:
        return 8
    if any(k in text for k in ("运单", "地址", "优惠", "发货")):
        return 7
    if "购物车" in text:
        return 5
    return 4


async def run_agent(job: AgentJobInput) -> dict:
    thread_id = job.thread_id
    user_id = job.user_id
    input_message = job.message
    job_id = job.job_id

    # 租户上下文注入(A7):先以作业声明值立上下文,后续线程行自愈出真实值
    # 再覆写 —— 深层记忆/领域工具的 ``or "ecommerce"`` 兜底从此优先吃上下文。
    # 协程内 set 只影响本任务上下文副本,不跨作业泄漏,故无需 reset。
    set_business_context(job.business_id)

    short_memory = ShortMemory(thread_id, 10, job.business_id)
    task_memory = TaskMemory(thread_id)

    # 0. 「继续」确定性重派(ADR-0013):上轮 assistant 缺失/失败时改写回
    # 上轮用户原问题,落回正常全链;五闸任一不过原样放行
    input_message = await _maybe_continue_rewrite(job, input_message, short_memory, task_memory)

    # 1. 🚀 毫秒级极速直达旁路:纯问候/身份问句零模型开销
    if is_quick_greeting(input_message):
        # P9(2026-10-03):问候旁路曾对同一行三连串行 DB 往返(SELECT 自愈 →
        # onboarding → _ensure_thread upsert)。现 upsert 带 RETURNING 一次拿到
        # 权威 business_id(ON CONFLICT 只续 updated_at 不覆盖归属 —— 返回值即
        # 库内真源,归属冻结不变量原样),往返 3→2;onboarding 仍需权威值后
        # 解析(问候文案按租户),保留串行。
        resolved_biz_id = job.business_id or "ecommerce"
        try:
            async with get_session() as session:
                stored_business_id = (
                    await session.execute(
                        text(
                            'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                            "VALUES (:tid, :uid, :bid, 'active', NOW(), NOW()) "
                            'ON CONFLICT (id) DO UPDATE SET "updated_at" = NOW() '
                            'RETURNING "business_id"'
                        ).bindparams(tid=thread_id, uid=user_id, bid=resolved_biz_id)
                    )
                ).scalar()
                if stored_business_id:
                    resolved_biz_id = stored_business_id
        except Exception as g_err:
            print(f"[Quick Greeting] Failed to resolve thread businessId: {g_err}")
        set_business_context(resolved_biz_id)  # 自愈值覆写(A7)

        # 同源改造(new-user-onboarding D):罐头回复消费租户 onboarding_config,
        # 与建线程欢迎行/回访轻问候同一份配置 —— 杜绝两套自我介绍。
        onboarding = await resolve_onboarding_config(resolved_biz_id)
        greeting_text = onboarding["welcomeText"]
        greeting_cards = build_entry_cards(onboarding)

        # 用户行归网关持久化(005 治理):旁路只落问候 assistant 行(带入口卡)。
        # T3(2026-10-03 重核):旁路落库失败自吞不炸问候(纯旁路无 LLM 成本,
        # 落库失败不该把秒级问候变成 5xx)。
        try:
            await short_memory.add_message("assistant", greeting_text, cards=greeting_cards)
        except Exception as mem_err:
            print(f"[runAgent] 问候旁路 assistant 行落库失败(不阻断): {mem_err!r}")

        greeting_result = {
            "output": greeting_text,
            "cards": greeting_cards,
            "taskPlan": {
                "goal": "Bypass planner loop and respond to quick greeting directly",
                "subtasks": [
                    {
                        "id": "respond_greeting",
                        "description": "Lightning bypass welcome message",
                        "status": "completed",
                        "result": {"message": "Bypassed successfully"},
                    }
                ],
                "currentStepIndex": 1,
            },
        }

        if job_id:
            # T3:旁路发布失败臂 —— 事件总线不可达时问候照常交付(sync 返回值
            # 完整),与主链 settle 的发布护栏同纪律;旁路曾裸奔,Redis 故障 =
            # 问候作业直接抛错。
            try:
                await emit_status(
                    job_id,
                    "极速通道：已秒级识别您所发送的日常打招呼，为您载入高画质欢迎界面...",
                    node="triage",
                    plan=greeting_result["taskPlan"],
                )
                await asyncio.sleep(0.1)
                await emit_job_result(job_id, greeting_text, greeting_result["taskPlan"], greeting_cards)
            except Exception as pub_err:
                print(f"[runAgent] 问候旁路事件发布失败(sync 返回值仍完整): {pub_err!r}")

        return greeting_result

    # 2. 🔍 三路 RAG 与记忆检索(文本过短时跳过,节省 1.5s+ 首字延迟)
    long_facts: list = []
    episodic_events: list = []
    rag_docs: list = []
    precomputed_embedding: list[float] | None = None

    # P4(2026-10-03):租户解析(线程自愈+配置读取,多次 DB 往返)与问句
    # embedding 互相独立 —— 旧实现串行 await 白付一段时延,gather 并行;
    # embedding 失败自吞为 None(三路检索各自无 embedding 降级语义不变)。
    async def _precompute_embedding() -> list[float] | None:
        if len(input_message.strip()) <= 3:
            return None
        try:
            return await get_embedding_model().aembed_query(input_message)
        except Exception as embed_err:
            print(f"[runAgent] Failed to precompute embedding for Single-Embedding Injection: {embed_err}")
            return None

    (business_id, dynamic_config), precomputed_embedding = await asyncio.gather(
        _resolve_business_context(thread_id, user_id, job.business_id),
        _precompute_embedding(),
    )
    set_business_context(business_id)  # 线程行自愈后的权威值覆写(A7)

    # LLM 调用归因:本次运行内全部模型调用(图节点 + 后台画像审计任务)据此
    # 落盘 llm_call_logs 的 thread_id / business_id(见 llm/telemetry.py);
    # job_id 供韧性层发布 ${jobId}:status 状态事件(见 llm/resilience.py)
    bind_llm_call_context(thread_id=thread_id, business_id=business_id, job_id=job_id)

    long_memory = LongMemory(user_id, business_id)
    episodic_memory = EpisodicMemory(user_id, business_id)

    if len(input_message.strip()) > 3:
        contextual_rag = ContextualRAG(business_id)

        facts_res, events_res, rag_res = await asyncio.gather(
            long_memory.search_relevant_facts(input_message, precomputed_embedding),
            episodic_memory.retrieve_events(input_message, 3, precomputed_embedding),
            contextual_rag.search_relevant_docs(input_message, 2, precomputed_embedding),
            return_exceptions=True,
        )
        long_facts = [] if isinstance(facts_res, Exception) else facts_res
        episodic_events = [] if isinstance(events_res, Exception) else events_res
        rag_docs = [] if isinstance(rag_res, Exception) else rag_res

    is_resuming = input_message.startswith("System:")
    # 用户行持久化归网关(dispatch/SPI,带 imageUrls;005 治理)——引擎零写用户行,
    # 否则每条消息时间线双插(user×2,一行带图一行不带)
    history_msgs = await short_memory.get_messages()

    # 恢复挂起任务状态与领域上下文
    saved_task_plan = None
    saved_guide_context = None
    saved_cart_context = None
    saved_order_context = None
    history_summary_prev = None
    try:
        saved_state = await task_memory.get_task_state()
        if saved_state:
            if is_resuming:
                saved_task_plan = saved_state
            saved_guide_context = saved_state.get("guideContext")
            saved_cart_context = saved_state.get("cartContext")
            saved_order_context = saved_state.get("orderContext")
            history_summary_prev = saved_state.get("historySummary")
    except Exception as err:
        print(f"[buildGraph] Failed to load saved task plan from taskMemory: {err}")

    # 历史预算 + 懒触发滚动摘要(2026-09-21 拷问轮决议):预算内零摘要成本;
    # 溢出那一刻把最老轮次压缩成 [EARLIER SUMMARY],每轮至多一次 LLM 调用,
    # 新摘要经 task_memory.historySummary 跨轮持久化;失败回退旧摘要不阻断。
    history_summary_final = history_summary_prev
    history_block = None
    try:
        built = build_history_block(history_msgs, summary=history_summary_prev)
        if built["trimmed"]:
            history_summary_final = await summarize_overflow(history_summary_prev, built["overflow"])
            # 触发轮新摘要即时渲染进本轮 block(否则溢出轮在当轮无声消失,下一轮才可见)
            history_block = build_history_block(history_msgs, summary=history_summary_final)["block"]
        else:
            history_block = built["block"]
    except Exception as ctx_err:
        print(f"[buildGraph] 历史预算装配失败,回退节点内裸拼: {ctx_err!r}")

    initial_state: AgentState = {
        "thread_id": thread_id,
        "user_id": user_id,
        "job_id": job_id or f"job_local_{int(time.time() * 1000)}",
        "input": input_message,
        "image_urls": normalize_image_urls(job.image_urls),
        "input_embedding": precomputed_embedding or [],
        "long_memory_facts": long_facts,
        "episodic_events": episodic_events,
        "rag_documents": rag_docs,
        "business_config": dynamic_config,
        "short_memory": history_msgs,
        "history_block": history_block,
        "task_plan": saved_task_plan if saved_task_plan is not None else dict(DEFAULT_TASK_PLAN),
        "loop_count": 0,
    }
    if saved_guide_context is not None:
        initial_state["guide_context"] = saved_guide_context
    if saved_cart_context is not None:
        # addedThisTurn 回合初剥离(2026-09-15 复合「加购+下单」范围结算):
        # 该标记只描述「本轮技能加购的行」,上一轮的残留若带入,本轮裸「下单」
        # 会被错误范围化成只结上一轮的加购(整车契约破坏)。本轮技能一旦执行
        # 加购即重写此键,跨轮语义由 run_agent 收口的 cartContext 整体落库承担。
        initial_state["cart_context"] = {
            k: v for k, v in saved_cart_context.items() if k != "addedThisTurn"
        }
    if saved_order_context is not None:
        initial_state["order_context"] = saved_order_context

    # 商城车水合(2026-09-14 空车谎报收口):商城页加购只写浏览器 localStorage,
    # 引擎车在 Redis —— 不水合则聊天侧删除/结算/查看只见空车。幂等合并:引擎车
    # 已有的 skuCode 跳过(聊天侧数量权威),失败降级空车照常,绝不阻断主链路。
    if job.store_cart:
        try:
            await MallDomainService.hydrate_cart_from_storefront(
                {"userId": user_id, "threadId": thread_id, "items": job.store_cart}
            )
        except Exception as hydrate_err:
            print(f"[runAgent] 商城车水合异常,忽略: {hydrate_err!r}")

    if job_id:
        await publish_agent_event(
            job_id, "status", {"status": "running", "message": "Local LangGraph execution engine initialized"}
        )

    start_time = time.time()
    graph_app = build_graph()
    llm_breaker_fired = False
    llm_quota_fired = False
    graph_error_fired = False
    interrupted = False
    # S2c/S2b:作业入活跃登记表 —— 网关取消路由(03 号票)的 request_cancel 只有
    # 打在活跃表上的作业才生效;owner 记派发身份(权威租户:用户,线程行自愈后的
    # business_id)供网关属主闸,记账侧与比对侧同归一(小写 strip 的 business 段)
    # 防大小写差自伤 403;返回(含降级/异常臂)即注销,挂起作业天然不可取消
    register_run(job_id, owner=f"{business_id.strip().lower()}:{user_id.strip()}")
    try:
        # 检查点化执行(S2c):ainvoke → astream 步间查取消闸;不取消时行为
        # 与 ainvoke 等价,取消命中返回最后完成步的部分态(interrupted=True)
        result, interrupted = await run_graph_with_interruption(graph_app, initial_state, job_id)
        if interrupted:
            # 部分态无 finish 终稿:严禁把中间产物冒充输出交付 —— output 清空,
            # 收口据此跳过 assistant 行落库(时间线无回答 → 「继续」确定性重派
            # 可接力,ADR-0013② 同构);任务记忆仍落,领域上下文跨轮延续。
            result = {**result, "output": ""}
    except CircuitBreakerOpenError as breaker_err:
        # 🛡️ 上游 LLM 熔断(连续失败达阈值,见 llm/resilience.py):全图中止,
        # 降级为道歉回复;session_metrics 落 resolution_status='llm_circuit_breaker'
        # (ticket 006 熔断信号入池的数据源)。韧性层已发布 circuit_breaker_open 状态事件。
        print(f"[runAgent] ⚠️ 上游 LLM 熔断,降级道歉回复: {breaker_err}")
        llm_breaker_fired = True
        result = _degraded_apology_result()
        # 确定性兜底分发器(2026-09-19「兜底什么回答什么」):词面可路由的
        # 问题(优惠/券/订单状态)仍给出真实答案,只有无能力命中才保留罐头
        try:
            from .skills.fallback_dispatcher import deterministic_fallback_answer

            fallback_output = await deterministic_fallback_answer(
                input_message, thread_id, user_id, job.business_id
            )
            if fallback_output:
                result = {**result, "output": fallback_output}
        except Exception as fb_err:
            print(f"[runAgent] 确定性兜底失败,保留道歉罐头: {fb_err}")
    except LlmQuotaError as quota_err:
        # 🚨 供应商账户额度缺额(code 1113,2026-10-15 夜评台账 #2):独立于
        # 熔断/图异常的第三降级臂 —— 文案如实点名额度限制,session_metrics 落
        # resolution_status='llm_quota_exhausted'(排障口径与用户所见同源,
        # 严禁混入「上游模型波动」)。
        print(f"[runAgent] 🚨 供应商账户额度缺额,降级道歉回复: {quota_err}")
        llm_quota_fired = True
        result = _degraded_apology_result("llm_quota")
        try:
            from .skills.fallback_dispatcher import deterministic_fallback_answer

            fallback_output = await deterministic_fallback_answer(
                input_message, thread_id, user_id, job.business_id
            )
            if fallback_output:
                result = {**result, "output": fallback_output}
        except Exception as fb_err:
            print(f"[runAgent] 确定性兜底失败,保留道歉罐头: {fb_err}")
    except Exception as graph_err:
        # 拓宽降级网(2026-09-12):图中任一未捕获异常(如上游 429 重试耗尽、
        # 单节点 bug)不得穿透为网关 500 / SSE 流挂死 —— 与熔断同形道歉降级。
        # 独立旗标 graph_error_fired:session_metrics 落 graph_error_degraded,
        # 严禁把降级作业记成 resolved_auto 成功(遥测如实,双轴审查工单)。
        print(f"[runAgent] ⚠️ 图执行未捕获异常,降级道歉回复: {graph_err!r}")
        graph_error_fired = True
        result = _degraded_apology_result("graph_error")
        try:
            from .skills.fallback_dispatcher import deterministic_fallback_answer

            fallback_output = await deterministic_fallback_answer(
                input_message, thread_id, user_id, job.business_id
            )
            if fallback_output:
                result = {**result, "output": fallback_output}
        except Exception as fb_err:
            print(f"[runAgent] 确定性兜底失败,保留道歉罐头: {fb_err}")
    finally:
        unregister_run(job_id)
    elapsed_latency_ms = (time.time() - start_time) * 1000

    # 收口(内部缝,ADR-0007):图后持久化段整体内聚在 _settle_turn —— 遥测/
    # 坏例/反幻觉闸/卡片/记忆/任务记忆/结果事件,顺序即契约。身份实参显式
    # 递入:降级臂结果没有 business_config,收口不得依赖图终态携带租户。
    return await _settle_turn(
        result,
        job=job,
        business_id=business_id,
        llm_breaker_fired=llm_breaker_fired,
        llm_quota_fired=llm_quota_fired,
        graph_error_fired=graph_error_fired,
        elapsed_latency_ms=elapsed_latency_ms,
        saved_guide_context=saved_guide_context,
        saved_cart_context=saved_cart_context,
        saved_order_context=saved_order_context,
        history_summary_final=history_summary_final,
        interrupted=interrupted,
    )
