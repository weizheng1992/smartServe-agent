"""双退款事故回放红灯回路(2026-09-05 19:08 事故,diagnosing-bugs Phase 1)。

事故链(全链路已由 DB 证据钉死,线程 merchant_thread_CUST-8801_aurora_1788076908973):
  用户「我想申请退款」(未指明订单,想退的是 9081)
  → slot_extractor.extract_order_id 历史反向扫描(含 assistant 消息)回填
    orderId=AURORA-ORD-2026-9082 —— 该单在旧回合(04:16)早已退款
  → missingSlots=[] 不澄清;planner fast-path 生成「Call processRefund for order 9082」
  → check_double_refund 只查 engine orders 表(AURORA 真单在 agent_merchant)→ 放行
  → evaluate_pending_approval_state 复用同线程 03:07 旧 approved 工单 → 不发新 HITL
  → process_refund 无 REFUNDED 幂等校验 → merchant_orders 物理重退(updated_at 11:08:53)

两个测试分别在两个缝上断言(现状红,修复后转绿):
  - test_refund_replay_executor_guard:已退款商户真单禁止被静默重退(执行器缝)
  - test_refund_intent_without_order_id_must_clarify:未指明订单号的退款意图必须澄清(槽位缝)
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.graph.nodes.step_execution_engine import execute_step

REPRO_THREAD = "dbg_repro_thread_double_refund"
REPRO_USER = "CUST-REPRO-1"
REPRO_ORDER = "AURORA-ORD-2026-9082"
# 事故时刻商户真单的物理指纹:04:16 首次退款落库时间(UTC)
PINNED_UPDATED_AT = "2026-09-05 04:16:14+00"

INCIDENT_SHORT_MEMORY = [
    {"role": "user", "content": "帮我申请订单 AURORA-ORD-2026-9082 的退款"},
    {"role": "assistant", "content": "已为您提交订单 AURORA-ORD-2026-9082 的退款申请,正在等待审核。"},
    {"role": "assistant", "content": "您的退款申请已成功处理,订单 AURORA-ORD-2026-9082 现已进入「已退款」状态。"},
]

_MERCHANT_DDL = """
CREATE TABLE IF NOT EXISTS merchant_orders (
    order_id text PRIMARY KEY,
    customer_id text NOT NULL,
    status text NOT NULL,
    total_amount numeric NOT NULL DEFAULT 0,
    currency text DEFAULT 'CNY',
    tracking_info jsonb DEFAULT '{}',
    shipping_address jsonb DEFAULT '{}',
    is_returnable boolean DEFAULT TRUE,
    is_address_modifiable boolean DEFAULT TRUE,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
)
"""


async def _setup(pg_factory):
    """密封 PG + 商户镜像表 + 事故前状态(9082 已退款、线程上有旧 approved 工单)。"""
    from engine_py.tools_registry import order_domain

    engine = pg_factory.kw["bind"]
    # str(engine.url) 会把密码打码为 ***,必须显式保留凭据
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        await conn.execute(text(_MERCHANT_DDL))
        await conn.execute(text("TRUNCATE merchant_orders"))
        await conn.execute(
            text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                "is_returnable, is_address_modifiable, created_at, updated_at) "
                "VALUES (:oid, :uid, 'REFUNDED', 1299, 'CNY', TRUE, TRUE, "
                "'2026-09-04 10:00:00+00', CAST(:pinned AS timestamptz))"
            ).bindparams(oid=REPRO_ORDER, uid=REPRO_USER, pinned=PINNED_UPDATED_AT)
        )

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM pending_approvals WHERE thread_id = :t").bindparams(t=REPRO_THREAD))
        await conn.execute(
            text(
                "INSERT INTO threads (id, user_id, business_id, status, created_at, updated_at) "
                "VALUES (:t, :u, 'aurora', 'active', now(), now()) "
                "ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id, updated_at = now()"
            ).bindparams(t=REPRO_THREAD, u=REPRO_USER)
        )
        await conn.execute(
            text(
                "INSERT INTO pending_approvals (thread_id, business_id, action_type, action_payload, "
                "status, deadline, created_at) VALUES (:t, 'aurora', 'processRefund', "
                "CAST(:payload AS jsonb), 'approved', now() + interval '1 day', '2026-09-05 03:07:46')"
            ).bindparams(
                t=REPRO_THREAD,
                payload=f'{{"args": {{"orderId": "{REPRO_ORDER}", "reason": "全额退款"}}}}',
            )
        )

    original = order_domain._merchant_reader_engine
    order_domain._merchant_reader_engine = lambda: merchant_engine
    return engine, merchant_engine, original


async def _teardown(engine, merchant_engine, original):
    from engine_py.tools_registry import order_domain

    order_domain._merchant_reader_engine = original
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM pending_approvals WHERE thread_id = :t").bindparams(t=REPRO_THREAD))
        # 挂起即落库(wayfinder 004)后 execute_step 也会写 task_memory,
        # 须先清子行否则 threads 删除触发外键
        await conn.execute(text("DELETE FROM task_memory WHERE thread_id = :t").bindparams(t=REPRO_THREAD))
        await conn.execute(text("DELETE FROM threads WHERE id = :t").bindparams(t=REPRO_THREAD))
    await merchant_engine.dispose()


def test_refund_replay_executor_guard(pg_factory):
    """回放事故执行链:planner fast-path 计划 + 陈旧 approved 工单 + 已退款商户真单。

    断言(现状红):已 REFUNDED 的商户真单不得被物理重退,也不得静默返回退款成功。
    """
    asyncio.run(_executor_scenario(pg_factory))


async def _executor_scenario(pg_factory):
    engine, merchant_engine, original = await _setup(pg_factory)
    try:
        state = {
            "thread_id": REPRO_THREAD,
            "user_id": REPRO_USER,
            "job_id": None,  # 关闭 emit_status,不依赖 Redis
            "input": "我想申请退款",
            "business_config": {"businessId": "aurora", "refundAutoApprovalLimit": 100},
            "intents": [{"intent": "order_return", "confidence": 0.95}],
            "short_memory": list(INCIDENT_SHORT_MEMORY),
            "task_plan": {
                "goal": f"Process refund for order {REPRO_ORDER}",
                "subtasks": [
                    {
                        "id": "step_fast_refund",
                        "description": f"Call processRefund for order {REPRO_ORDER}",
                        "status": "pending",
                    }
                ],
                "currentStepIndex": 0,
            },
        }

        result = await execute_step(state)

        step = (result.get("taskPlan") or {}).get("subtasks", [{}])[0]
        output = (step.get("result") or {}).get("output") or {}

        async with merchant_engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT status, updated_at FROM merchant_orders WHERE order_id = :o").bindparams(
                            o=REPRO_ORDER
                        )
                    )
                )
                .mappings()
                .first()
            )

        # 症状断言 1:商户真单不得被物理改写(现状红:updated_at 被刷成 now())
        assert row["updated_at"].isoformat() == _as_iso(PINNED_UPDATED_AT), (
            f"已退款订单被物理重退:updated_at {row['updated_at']} ≠ 首次退款时间"
        )
        # 症状断言 2:不得静默宣称退款成功(现状红:status=completed + output.status=refunded)
        assert not (step.get("status") == "completed" and output.get("status") == "refunded"), (
            f"无新审批即静默完成重退:{step.get('status')} / {output}"
        )
    finally:
        await _teardown(engine, merchant_engine, original)


def _as_iso(ts: str) -> str:
    from datetime import datetime

    return datetime.fromisoformat(ts).isoformat()


def test_ghost_order_refund_fails_honestly_without_ticket(pg_factory):
    """幽灵单前置拦截(2026-09-09 OCR 事故收口):随手图片里 OCR 出的 ORD-XXXXX
    或文本里随手敲的单号,若三库查无此单,审批门前必须诚实失败 —— 旧行为是
    直接开 waiting 工单并谎称"已为您发起退款申请"(实弹:ORD-77777/ORD-99999
    均落幽灵工单)。"""
    asyncio.run(_ghost_order_scenario(pg_factory))


async def _ghost_order_scenario(pg_factory):
    engine, merchant_engine, original = await _setup(pg_factory)
    try:
        # 清掉 _setup 播种的旧 approved 工单,保证计数口径干净
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM pending_approvals WHERE thread_id = :t").bindparams(t=REPRO_THREAD)
            )
        before_count = await _approval_count(engine)

        state = {
            "thread_id": REPRO_THREAD,
            "user_id": REPRO_USER,
            "job_id": None,  # 关闭 emit_status,不依赖 Redis
            "input": "坏了",
            "business_config": {"businessId": "aurora", "refundAutoApprovalLimit": 100},
            "intents": [{"intent": "refund", "confidence": 0.95}],
            "short_memory": [],
            "task_plan": {
                "goal": "Process refund for order ORD-77777",
                "subtasks": [
                    {
                        "id": "step_refund",
                        "description": "Call processRefund for order ORD-77777",
                        "status": "pending",
                    }
                ],
                "currentStepIndex": 0,
            },
        }

        result = await execute_step(state)
        step = (result.get("taskPlan") or {}).get("subtasks", [{}])[0]
        result_msg = str((step.get("result") or {}).get("message") or "")
        after_count = await _approval_count(engine)

        assert step.get("status") == "failed", (
            f"幽灵单必须诚实失败,实际 status={step.get('status')} message={result_msg!r}"
        )
        assert "ORD-77777" in result_msg, f"失败话术须带单号便于用户核对:{result_msg!r}"
        assert after_count == before_count, (
            f"幽灵单不得开审批工单:before={before_count} after={after_count}"
        )
    finally:
        await _teardown(engine, merchant_engine, original)


def test_stale_approved_ticket_must_not_authorize_new_refund(pg_factory):
    """钉住 HITL 旁路封死:同线程同订单的旧 approved 工单(已批准但从未执行的残余)
    不得授权新一次退款 —— 必须重新开 waiting 工单走人工审核。"""
    asyncio.run(_stale_ticket_scenario(pg_factory))


async def _stale_ticket_scenario(pg_factory):
    engine, merchant_engine, original = await _setup(pg_factory)
    try:
        # 场景改造:9081 尚未退款(PAID),线程上有其旧 approved 残余工单
        async with merchant_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                    "is_returnable, is_address_modifiable, created_at, updated_at) "
                    "VALUES ('AURORA-ORD-2026-9081', :uid, 'PAID', 1299, 'CNY', TRUE, TRUE, "
                    "'2026-09-04 10:00:00+00', '2026-09-05 04:00:00+00')"
                ).bindparams(uid=REPRO_USER)
            )
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO pending_approvals (thread_id, business_id, action_type, action_payload, "
                    "status, deadline, created_at) VALUES (:t, 'aurora', 'processRefund', "
                    "CAST(:payload AS jsonb), 'approved', now() + interval '1 day', '2026-09-05 03:00:00')"
                ).bindparams(t=REPRO_THREAD, payload='{"args": {"orderId": "AURORA-ORD-2026-9081"}}')
            )

        before_count = await _approval_count(engine)

        state = {
            "thread_id": REPRO_THREAD,
            "user_id": REPRO_USER,
            "job_id": None,
            "input": "帮我申请订单 AURORA-ORD-2026-9081 的退款",
            "business_config": {"businessId": "aurora", "refundAutoApprovalLimit": 100},
            "intents": [{"intent": "order_return", "confidence": 0.95}],
            "short_memory": list(INCIDENT_SHORT_MEMORY),
            "task_plan": {
                "goal": "Process refund for order AURORA-ORD-2026-9081",
                "subtasks": [
                    {
                        "id": "step_fast_refund",
                        "description": "Call processRefund for order AURORA-ORD-2026-9081",
                        "status": "pending",
                    }
                ],
                "currentStepIndex": 0,
            },
        }
        result = await execute_step(state)

        step = (result.get("taskPlan") or {}).get("subtasks", [{}])[0]
        after_count = await _approval_count(engine)

        # 断言 1:必须新开 waiting 工单,而不是复用旧 approved 静默放行
        assert after_count == before_count + 1, f"应新开审批工单: {before_count} → {after_count}"
        # 断言 2:步骤挂起等待人工,未物理执行
        assert (step.get("result") or {}).get("waitingForApproval") is True, (
            f"步骤应挂起等待审批,实际: {step.get('status')} / {step.get('result')}"
        )
        async with merchant_engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text("SELECT status FROM merchant_orders WHERE order_id = 'AURORA-ORD-2026-9081'")
                    )
                )
                .mappings()
                .first()
            )
        assert row["status"] == "PAID", f"未获新审批前订单不得被退款,实际状态: {row['status']}"
    finally:
        await _teardown(engine, merchant_engine, original)


async def _approval_count(engine) -> int:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT count(*) FROM pending_approvals WHERE thread_id = :t").bindparams(t=REPRO_THREAD)
            )
        ).scalar()


def test_refund_survives_timezone_aware_delivery_date(pg_factory):
    """回归钉(wayfinder 004):estimated_delivery 为带时区偏移的文本
    (PG NOW() 写入 text 列 / 商户 SPI ISO 串)时,时效比对不得 TypeError 炸掉退款。

    修复前:fromisoformat 解析出 aware datetime,与 naive 的 datetime.now() 相减
    直接崩溃,HITL 核签通过后的退款恢复执行整段静默死亡(消息永不落库)。
    """
    asyncio.run(_tz_aware_delivery_scenario(pg_factory))


async def _tz_aware_delivery_scenario(pg_factory):
    from engine_py.tools_registry.order_domain import OrderDomainService

    engine = pg_factory.kw["bind"]
    tz_thread, tz_user, tz_order = "dbg_tz_thread_refund", "CUST-TZ-1", "ORD-TZ-WINDOW"
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO threads (id, user_id, business_id, status) VALUES (:t, :u, 'ecommerce', 'active') "
                    "ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id"
                ).bindparams(t=tz_thread, u=tz_user)
            )
            # NOW() 写入 text 列 → 值形如 '2026-09-04 09:56:12.123+00'(带偏移),复现种子事故形态
            await conn.execute(
                text(
                    "INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery, "
                    "user_id, business_id, total_amount) VALUES (:oid, 'delivered', 'FedEx', 'TRK-TZ', "
                    "CAST((NOW() - INTERVAL '3 days') AS text), :u, 'ecommerce', 199.96) "
                    "ON CONFLICT (order_id) DO UPDATE SET status = 'delivered', "
                    "estimated_delivery = EXCLUDED.estimated_delivery, user_id = EXCLUDED.user_id"
                ).bindparams(oid=tz_order, u=tz_user)
            )

        result = await OrderDomainService.process_refund(tz_order, "商品质量问题", tz_thread)

        assert "error" not in result, f"带时区送达日期不得炸退款: {result}"
        async with engine.connect() as conn:
            status = (
                await conn.execute(
                    text("SELECT status FROM orders WHERE order_id = :oid").bindparams(oid=tz_order)
                )
            ).scalar()
        assert status == "refunded", f"3 天 < 7 天时效窗口,应真实执行退款,实际状态: {status}"
    finally:
        # 断言失败也要清理本用例私有线程/订单,避免残留行污染同库后续回放
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM orders WHERE order_id = :oid").bindparams(oid=tz_order))
            await conn.execute(text("DELETE FROM threads WHERE id = :tid").bindparams(tid=tz_thread))


def test_refund_intent_without_order_id_must_clarify():
    """回放事故槽位提取:当前输入无订单号 + 用户有多笔订单 → 必须追问,不得回填历史订单号。

    断言(现状红):slots.orderId 被旧回合 assistant 消息回填为 9082 且 missingSlots 为空。
    """
    from engine_py.triage.slot_extractor import SlotExtractor

    result = SlotExtractor.extract(
        "我想申请退款",
        None,
        None,
        {"historyMsgs": list(INCIDENT_SHORT_MEMORY)},
    )

    assert not result["slots"].get("orderId"), (
        f"当前输入未指明订单号,却从历史回填了 {result['slots'].get('orderId')}"
    )
    assert "orderId" in result["missingSlots"], (
        f"应追问订单号,实际 missingSlots={result['missingSlots']}"
    )


def test_suspension_persists_task_plan_immediately(pg_factory):
    """回归钉(wayfinder 004):步骤挂起等待审批的瞬间,挂起计划必须已写入 task_memory。

    事故形态:审批工单创建后对前端 2s 轮询立即可见,人工秒级核签派发的
    job_resume_* 在挂起运行收口(save_task_state)之前启动 → 恢复读到空计划,
    triage 的 System: 分支误判 order_status 直接查单,退款永不执行。
    计划持久化必须与审批可见性同一时刻成立,不得依赖运行收口。
    """
    asyncio.run(_suspension_persist_plan_scenario(pg_factory))


async def _suspension_persist_plan_scenario(pg_factory):
    from engine_py.memory.task_memory import TaskMemory

    engine, merchant_engine, original = await _setup(pg_factory)
    thread = "dbg_suspend_persist_thread"
    order = "AURORA-ORD-2026-9083"
    try:
        async with merchant_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                    "is_returnable, is_address_modifiable, created_at, updated_at) "
                    "VALUES (:o, :u, 'PAID', 1299, 'CNY', TRUE, TRUE, "
                    "'2026-09-04 10:00:00+00', '2026-09-05 04:00:00+00')"
                ).bindparams(o=order, u=REPRO_USER)
            )
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM pending_approvals WHERE thread_id = :t").bindparams(t=thread))
            await conn.execute(text("DELETE FROM task_memory WHERE thread_id = :t").bindparams(t=thread))
            await conn.execute(
                text(
                    "INSERT INTO threads (id, user_id, business_id, status, created_at, updated_at) "
                    "VALUES (:t, :u, 'aurora', 'active', now(), now()) "
                    "ON CONFLICT (id) DO UPDATE SET user_id = EXCLUDED.user_id, updated_at = now()"
                ).bindparams(t=thread, u=REPRO_USER)
            )

        state = {
            "thread_id": thread,
            "user_id": REPRO_USER,
            "job_id": None,
            "input": f"帮我申请订单 {order} 的退款",
            "business_config": {"businessId": "aurora", "refundAutoApprovalLimit": 100},
            "intents": [{"intent": "order_return", "confidence": 0.95}],
            "short_memory": [{"role": "user", "content": f"帮我申请订单 {order} 的退款"}],
            "task_plan": {
                "goal": f"Process refund for order {order}",
                "subtasks": [
                    {
                        "id": "step_fast_refund",
                        "description": f"Call processRefund for order {order}",
                        "status": "pending",
                    }
                ],
                "currentStepIndex": 0,
            },
        }
        result = await execute_step(state)
        step = (result.get("taskPlan") or {}).get("subtasks", [{}])[0]
        assert (step.get("result") or {}).get("waitingForApproval") is True, (
            f"前置失败:步骤未挂起(需先复现 waiting 挂起才可断言计划落库),实际:{step}"
        )

        # 核心断言:挂起瞬间(未等运行收口)task_memory 已持有可恢复的挂起计划
        saved = await TaskMemory(thread).get_task_state()
        assert saved and saved.get("subtasks"), (
            f"挂起时 task_memory 为空({saved}),秒级核签的恢复将以空计划降级为查单"
        )
        saved_step = saved["subtasks"][0]
        assert (saved_step.get("result") or {}).get("waitingForApproval") is True
        assert (saved_step.get("result") or {}).get("approvalId"), "挂起计划须带 approvalId 供恢复匹配"
        assert "processRefund" in (saved_step.get("description") or "")
        assert saved.get("currentStepIndex") == 0
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM pending_approvals WHERE thread_id = :t").bindparams(t=thread))
            await conn.execute(text("DELETE FROM task_memory WHERE thread_id = :t").bindparams(t=thread))
            await conn.execute(text("DELETE FROM threads WHERE id = :t").bindparams(t=thread))
        await _teardown(engine, merchant_engine, original)
