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
from .db import BusinessConfigRow, SessionMetric, Thread, get_session
from .event_bus import emit_job_result, emit_status, publish_agent_event
from .graph import build_graph
from .graph.build_graph import CIRCUIT_BREAKER_TOOL_ERRORS, CIRCUIT_BREAKER_TRANSITIONS
from .graph.state import DEFAULT_TASK_PLAN, AgentState, to_ts_dict
from .llm import (
    CircuitBreakerOpenError,
    bind_llm_call_context,
    drain_llm_call_writes,
    get_embedding_model,
    take_thread_token_total,
)
from .memory import EpisodicMemory, LongMemory, ShortMemory, TaskMemory
from .onboarding import build_entry_cards, resolve_onboarding_config
from .rag import ContextualRAG
from .tenant import get_merchant_display_name
from .triage.rule_matchers import is_quick_greeting
from .vision import normalize_image_urls


class AgentJobInput(BaseModel):
    """作业输入 — 字段与 WorkflowOrchestrator.dispatchJob 的载荷对齐。"""

    job_id: str = Field(alias="jobId")
    thread_id: str = Field(alias="threadId")
    user_id: str = Field(default="CUST-8801", alias="userId")
    business_id: str = Field(default="ecommerce", alias="businessId")
    message: str
    image_urls: list[str] = Field(default_factory=list, alias="imageUrls")

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
        "refundAutoApprovalLimit": 100,
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
                # 自愈装配(Nike $150 / Adidas $120 / 主站 $100)
                default_limit = 150 if business_id == "nike" else 120 if business_id == "adidas" else 100
                dynamic_config = {**dynamic_config, "businessId": business_id, "refundAutoApprovalLimit": default_limit}
    except Exception as err:
        print(f"[SaaS Config Engine] Failed to dynamically load business config: {err}")

    return business_id, dynamic_config


def _degraded_llm_breaker_result() -> dict:
    """上游 LLM 熔断时的降级结果:道歉回复 + 空计划,沿用图终态消费链路。

    run_agent 主流程(metrics 落盘 / 任务记忆 / result 事件)继续走通,
    仅 resolution_status 落 ``llm_circuit_breaker``。
    """
    return {
        "output": (
            "非常抱歉,智能服务当前遇到上游模型波动,暂时无法处理您的请求。"
            "请稍后再试,或选择人工客服协助。"
        ),
        "task_plan": dict(DEFAULT_TASK_PLAN),
        "loop_count": 0,
        "global_transitions_count": 0,
        "tool_errors_count": 0,
    }


async def _report_langsmith_feedback(is_success: bool, comment: str) -> None:
    """后台 fire-and-forget 上报 LangSmith 语义反馈(TS 侧无 runId 桥接,标记简化)。"""
    api_key = os.environ.get("LANGCHAIN_API_KEY")
    if not api_key:
        return
    endpoint = os.environ.get("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    try:
        import httpx

        async with httpx.AsyncClient() as client:
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


async def run_agent(job: AgentJobInput) -> dict:
    thread_id = job.thread_id
    user_id = job.user_id
    input_message = job.message
    job_id = job.job_id

    short_memory = ShortMemory(thread_id, 10, job.business_id)
    task_memory = TaskMemory(thread_id)

    # 1. 🚀 毫秒级极速直达旁路:纯问候/身份问句零模型开销
    if is_quick_greeting(input_message):
        resolved_biz_id = job.business_id or "ecommerce"
        try:
            async with get_session() as session:
                thread_row = (
                    await session.execute(select(Thread).where(Thread.id == thread_id).limit(1))
                ).scalar_one_or_none()
                if thread_row and thread_row.business_id:
                    resolved_biz_id = thread_row.business_id
        except Exception as g_err:
            print(f"[Quick Greeting] Failed to resolve thread businessId: {g_err}")

        # 同源改造(new-user-onboarding D):罐头回复消费租户 onboarding_config,
        # 与建线程欢迎行/回访轻问候同一份配置 —— 杜绝两套自我介绍。
        onboarding = await resolve_onboarding_config(resolved_biz_id)
        greeting_text = onboarding["welcomeText"]
        greeting_cards = build_entry_cards(onboarding)

        try:
            await _ensure_thread(thread_id, user_id, job.business_id)
        except Exception as thread_err:
            print(f"[DB] Failed to ensure thread exists for quick greeting: {thread_err}")

        # 用户行归网关持久化(005 治理):旁路只落问候 assistant 行(带入口卡)
        await short_memory.add_message("assistant", greeting_text, cards=greeting_cards)

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
            await emit_status(
                job_id,
                "极速通道：已秒级识别您所发送的日常打招呼，为您载入高画质欢迎界面...",
                node="triage",
                plan=greeting_result["taskPlan"],
            )
            await asyncio.sleep(0.1)
            await emit_job_result(job_id, greeting_text, greeting_result["taskPlan"], greeting_cards)

        return greeting_result

    # 2. 🔍 三路 RAG 与记忆检索(文本过短时跳过,节省 1.5s+ 首字延迟)
    long_facts: list = []
    episodic_events: list = []
    rag_docs: list = []
    precomputed_embedding: list[float] | None = None

    business_id, dynamic_config = await _resolve_business_context(thread_id, user_id, job.business_id)

    # LLM 调用归因:本次运行内全部模型调用(图节点 + 后台画像审计任务)据此
    # 落盘 llm_call_logs 的 thread_id / business_id(见 llm/telemetry.py);
    # job_id 供韧性层发布 ${jobId}:status 状态事件(见 llm/resilience.py)
    bind_llm_call_context(thread_id=thread_id, business_id=business_id, job_id=job_id)

    long_memory = LongMemory(user_id, business_id)
    episodic_memory = EpisodicMemory(user_id, business_id)

    if len(input_message.strip()) > 3:
        contextual_rag = ContextualRAG(business_id)
        try:
            precomputed_embedding = await get_embedding_model().aembed_query(input_message)
        except Exception as embed_err:
            print(f"[runAgent] Failed to precompute embedding for Single-Embedding Injection: {embed_err}")

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
    try:
        saved_state = await task_memory.get_task_state()
        if saved_state:
            if is_resuming:
                saved_task_plan = saved_state
            saved_guide_context = saved_state.get("guideContext")
            saved_cart_context = saved_state.get("cartContext")
            saved_order_context = saved_state.get("orderContext")
    except Exception as err:
        print(f"[buildGraph] Failed to load saved task plan from taskMemory: {err}")

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
        "task_plan": saved_task_plan if saved_task_plan is not None else dict(DEFAULT_TASK_PLAN),
        "loop_count": 0,
    }
    if saved_guide_context is not None:
        initial_state["guide_context"] = saved_guide_context
    if saved_cart_context is not None:
        initial_state["cart_context"] = saved_cart_context
    if saved_order_context is not None:
        initial_state["order_context"] = saved_order_context

    if job_id:
        await publish_agent_event(
            job_id, "status", {"status": "running", "message": "Local LangGraph execution engine initialized"}
        )

    start_time = time.time()
    graph_app = build_graph()
    llm_breaker_fired = False
    try:
        result = await graph_app.ainvoke(initial_state)
    except CircuitBreakerOpenError as breaker_err:
        # 🛡️ 上游 LLM 熔断(连续失败达阈值,见 llm/resilience.py):全图中止,
        # 降级为道歉回复;session_metrics 落 resolution_status='llm_circuit_breaker'
        # (ticket 006 熔断信号入池的数据源)。韧性层已发布 circuit_breaker_open 状态事件。
        print(f"[runAgent] ⚠️ 上游 LLM 熔断,降级道歉回复: {breaker_err}")
        llm_breaker_fired = True
        result = _degraded_llm_breaker_result()
    elapsed_latency_ms = (time.time() - start_time) * 1000

    # 🪙 SaaS 遥测:算力消耗 / 成本换算 / 图决策深度 / 解挂状态
    try:
        # 等待本运行派发的 llm_call_logs 落盘任务收口,再取真实 usage 累计
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

        # 🛡️ LLM 熔断落盘(resilience.py 全局熔断器拦截):job 级终态,优先于图级判定
        if llm_breaker_fired:
            resolution_status = "llm_circuit_breaker"
            is_success = False
            feedback_comment = "Upstream LLM circuit breaker open; job degraded with apology fallback."
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
        if subtasks and not breaker_fired:
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
                    business_id=dynamic_config["businessId"],
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

        # 📥 熔断信号入坏例池(wayfinder 006):被熔断打断的会话以会话为评审
        # 单位入池(先验 suspected_defect,人审定性,见 badcase/pool.py)。
        # 挂点定案:run_agent 会话收口处而非状态机翻转处 —— 翻转可能发生在
        # 无会话归属的后台调用,而池以会话为评审单位,与 session_metrics
        # 熔断落盘(003 数据源)同位;dedupe=True 使 OPEN 窗口内同一会话多次
        # 回合只入池一次;入池失败静默降级不阻断主流程(内建)。
        if llm_breaker_fired or breaker_fired:
            await record_badcase_signal(
                SOURCE_CIRCUIT_BREAKER,
                conversation_ref=f"thread:{thread_id}",
                business_id=dynamic_config["businessId"],
                dedupe=True,
                note=(
                    "上游 LLM 熔断(OPEN)拦截,会话降级道歉回复"
                    if llm_breaker_fired
                    else f"图级熔断:全局转移 {global_transitions} 次 / 工具错误 {tool_errors} 次"
                ),
            )

        # 🔍 宣称与落库不符信号入池(intent-arbitration 02):终稿宣称已退款/
        # 已提交审批 × 审批表整会话零记录 → 候选行(先验 suspected_defect)。
        # ORD-77777 编造审批一类:幽灵单拦截挡住了开单,终稿幻觉的宣称仍要
        # 能被捕到;入池静默降级不阻断收口。
        await record_claim_mismatch_if_any(
            thread_id,
            dynamic_config["businessId"],
            str(result.get("output") or ""),
        )
    except Exception as metrics_err:
        print(f"[SaaS Telemetry] Failed to persist session metrics in physical table: {metrics_err}")

    # 🗂️ 富媒体卡片合成(已有卡片优先)
    synthesized_cards = CardSynthesizer.synthesize_cards(
        {
            "taskPlan": result.get("task_plan"),
            "intents": result.get("intents"),
            "damageAssessment": result.get("damage_assessment"),
        }
    )
    existing_cards = result.get("cards") or []
    final_cards = existing_cards if existing_cards else synthesized_cards

    # 助手回复回写三路记忆
    if result.get("output"):
        await short_memory.add_message("assistant", result["output"], final_cards)
        await episodic_memory.add_event(
            f"Handled conversation thread: {thread_id}. Output summary: {result['output'][:80]}", 5
        )
        await long_memory.extract_and_store_fact(result["output"], input_message)

    # 持久化任务记忆与领域上下文
    task_plan_to_save = result.get("task_plan") or {
        "goal": "Multi-turn conversational assistance",
        "subtasks": [],
        "currentStepIndex": 0,
    }
    await task_memory.save_task_state(
        {
            **task_plan_to_save,
            "guideContext": result.get("guide_context") or saved_guide_context,
            "cartContext": result.get("cart_context") or saved_cart_context,
            "orderContext": result.get("order_context") or saved_order_context,
        }
    )

    final_result = {**to_ts_dict(result), "cards": final_cards}

    if job_id:
        await publish_agent_event(job_id, "result", final_result)

    return final_result
