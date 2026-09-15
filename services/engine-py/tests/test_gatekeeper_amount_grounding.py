"""退款审批卡金额回照契约(admin-readiness 工单 11 / code-review 2026-09-14)。

评审钉死的缺口:P1 修复(建票时按 orderId 回查商户库快照真实 total_amount
落 args,商户盲批资金单不可接受)此前零自动化验证 —— 本套按三态钉死:
商户真单在库 → amount/currency/amountSource=merchant_orders_snapshot;
查无此单 → 诚实标注 order_not_found_in_merchant_db,严禁落 0 或编造;
库不可达 → lookup_unavailable 且异常留痕。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from engine_py.approvals.gatekeeper import ApprovalGatekeeper

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

_REAL_ORDER = "AURORA-ORD-2026-9001"
_MISSING_ORDER = "AURORA-ORD-2026-9999"


async def _setup(pg_factory, thread_id: str):
    """密封 PG + 商户镜像表(真实单 9001,¥1299 CNY)+ 线程行 + reader 打桩。"""
    from engine_py.tools_registry import order_domain

    engine = pg_factory.kw["bind"]
    url = engine.url.render_as_string(hide_password=False)
    merchant_engine = create_async_engine(url, poolclass=NullPool)

    async with merchant_engine.begin() as conn:
        await conn.execute(text(_MERCHANT_DDL))
        await conn.execute(
            text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency) "
                "VALUES (:oid, 'CUST-8801', 'PAID', 1299, 'CNY') ON CONFLICT (order_id) DO NOTHING"
            ).bindparams(oid=_REAL_ORDER)
        )

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO threads (id, user_id, business_id, status, created_at, updated_at) "
                "VALUES (:t, 'CUST-8801', 'aurora', 'active', now(), now()) "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(t=thread_id)
        )

    original = order_domain._merchant_reader_engine
    order_domain._merchant_reader_engine = lambda: merchant_engine
    return engine, merchant_engine, original


async def _teardown(engine, merchant_engine, original, thread_id: str):
    from engine_py.tools_registry import order_domain

    order_domain._merchant_reader_engine = original
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM pending_approvals WHERE thread_id = :t").bindparams(t=thread_id))
        await conn.execute(text("DELETE FROM task_memory WHERE thread_id = :t").bindparams(t=thread_id))
        await conn.execute(text("DELETE FROM messages WHERE thread_id = :t").bindparams(t=thread_id))
        await conn.execute(text("DELETE FROM threads WHERE id = :t").bindparams(t=thread_id))
    await merchant_engine.dispose()


async def _create_ticket_and_read_args(thread_id: str, order_id: str) -> dict:
    """走 evaluate_pending_approval_state 建票路径,回读落库的 action_payload.args。"""
    result = await ApprovalGatekeeper.evaluate_pending_approval_state(
        {
            "threadId": thread_id,
            "toolName": "processRefund",
            "args": {"orderId": order_id},
            "stepDescription": f"Call processRefund for order {order_id}",
            "stepIndex": 0,
        }
    )
    assert result["state"] == "waiting", result
    from engine_py.db import get_session  # 密封夹具替换后的会话工厂

    async with get_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT action_payload FROM pending_approvals "
                    "WHERE thread_id = :t AND action_type = 'processRefund' "
                    "ORDER BY created_at DESC LIMIT 1"
                ).bindparams(t=thread_id)
            )
        ).mappings().first()
    assert row is not None
    return (row["action_payload"] or {}).get("args") or {}


def test_refund_amount_grounded_from_merchant_snapshot(pg_factory):
    """商户真单在库:args 带真实金额快照,商户审批卡不再盲批。"""

    async def _scenario():
        thread_id = "gatekeeper_amount_grounded"
        engine, merchant_engine, original = await _setup(pg_factory, thread_id)
        try:
            args = await _create_ticket_and_read_args(thread_id, _REAL_ORDER)
            assert args["amount"] == 1299.0
            assert args["currency"] == "CNY"
            assert args["amountSource"] == "merchant_orders_snapshot"
        finally:
            await _teardown(engine, merchant_engine, original, thread_id)

    asyncio.run(_scenario())


def test_refund_amount_honestly_marked_when_order_missing(pg_factory):
    """查无此单:诚实标注,严禁落 0 或编造金额。"""

    async def _scenario():
        thread_id = "gatekeeper_amount_missing"
        engine, merchant_engine, original = await _setup(pg_factory, thread_id)
        try:
            args = await _create_ticket_and_read_args(thread_id, _MISSING_ORDER)
            assert "amount" not in args
            assert args["amountSource"] == "order_not_found_in_merchant_db"
        finally:
            await _teardown(engine, merchant_engine, original, thread_id)

    asyncio.run(_scenario())


def test_refund_amount_honestly_marked_when_merchant_db_unreachable(pg_factory):
    """商户库不可达:lookup_unavailable 标注,不阻断建票。"""

    async def _scenario():
        from engine_py.tools_registry import order_domain

        thread_id = "gatekeeper_amount_unreachable"
        engine, merchant_engine, original = await _setup(pg_factory, thread_id)

        def _boom():
            raise RuntimeError("merchant db down")

        order_domain._merchant_reader_engine = _boom
        try:
            args = await _create_ticket_and_read_args(thread_id, _REAL_ORDER)
            assert "amount" not in args
            assert args["amountSource"] == "lookup_unavailable"
        finally:
            order_domain._merchant_reader_engine = original
            await _teardown(engine, merchant_engine, original, thread_id)

    asyncio.run(_scenario())
