"""免签限额自动放行策略契约(ApprovalPolicyEngine.evaluate_refund_auto_approval)。

夜审 2026-10-02 测试缺口①(step_execution_engine §4.2 消费的钱数闸此前零覆盖):
- 限额内放行 / 超限不放行 / 边界(=限额放行);
- 「¥ 1,299.00」类脏格式金额解析;
- 无金额时按 orderId 回照 engine orders 快照 grounding;
- 查无此单 / 无参 / 解析为 0 / 不可解析 一律 fail-closed(groundedAmount
  999999.99 → 必走 HITL,绝无静默放行)。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from engine_py.approvals.gatekeeper import ApprovalGatekeeper

_FAIL_CLOSED_AMOUNT = 999999.99


# ---------- 纯策略:金额参数面(零 DB) ----------


def test_amount_within_limit_auto_approves():
    out = asyncio.run(ApprovalGatekeeper.evaluate_refund_auto_approval("ORD-1", "¥88.00", 100))
    assert out == {"shouldAutoApprove": True, "groundedAmount": 88.0}


def test_amount_over_limit_requires_approval():
    out = asyncio.run(ApprovalGatekeeper.evaluate_refund_auto_approval("ORD-1", "1299", 100))
    assert out == {"shouldAutoApprove": False, "groundedAmount": 1299.0}


def test_dirty_format_amount_parsed():
    """千分位/货币符/空白照常解析 —— 客户话术里的「¥ 1,299.00」不得绕闸。"""
    out = asyncio.run(ApprovalGatekeeper.evaluate_refund_auto_approval("ORD-1", "¥ 1,299.00", 100))
    assert out["groundedAmount"] == 1299.0 and out["shouldAutoApprove"] is False


def test_amount_equal_to_limit_auto_approves():
    """边界:限额本身放行(<= 语义,商户配置 100 即「100 及以内免签」)。"""
    out = asyncio.run(ApprovalGatekeeper.evaluate_refund_auto_approval("ORD-1", "100", 100))
    assert out["shouldAutoApprove"] is True and out["groundedAmount"] == 100.0


def test_missing_amount_fails_closed():
    """无金额且无单可回照 → 999999.99 fail-closed,必走 HITL。"""
    out = asyncio.run(ApprovalGatekeeper.evaluate_refund_auto_approval(None, None, 100))
    assert out["shouldAutoApprove"] is False and out["groundedAmount"] == _FAIL_CLOSED_AMOUNT


def test_zero_amount_fails_closed():
    """「¥0」不是合法免签退款:解析为 0 走 falsy 兜底 → 与无金额同口径。"""
    out = asyncio.run(ApprovalGatekeeper.evaluate_refund_auto_approval("ORD-1", "¥0", 100))
    assert out["shouldAutoApprove"] is False and out["groundedAmount"] == _FAIL_CLOSED_AMOUNT


def test_unparseable_amount_fails_closed():
    """纯字母「金额」剥不出数字 → fail-closed,不抛错不放行。"""
    out = asyncio.run(ApprovalGatekeeper.evaluate_refund_auto_approval("ORD-1", "abc元", 100))
    assert out["shouldAutoApprove"] is False and out["groundedAmount"] == _FAIL_CLOSED_AMOUNT


# ---------- grounding:无金额时回照 orders 快照(密封 PG) ----------


def _insert_order_sql(order_id: str, total: float | None) -> str:
    return (
        "INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery, "
        f"business_id, total_amount) VALUES ('{order_id}', 'processing', 'sf', 'SF001', '3天', "
        f"'ecommerce', {total if total is not None else 'NULL'})"
    )


def test_amount_grounded_from_orders_snapshot(pg_factory):
    """无金额参数 → 按 orderId 回照 engine orders 总额判定。"""

    async def _scenario():
        engine = pg_factory.kw["bind"]
        async with engine.begin() as conn:
            await conn.execute(text(_insert_order_sql("ORD-GROUND-1", 59.9)))
        return await ApprovalGatekeeper.evaluate_refund_auto_approval("ORD-GROUND-1", None, 100)

    out = asyncio.run(_scenario())
    assert out == {"shouldAutoApprove": True, "groundedAmount": 59.9}


def test_grounded_snapshot_over_limit(pg_factory):
    async def _scenario():
        engine = pg_factory.kw["bind"]
        async with engine.begin() as conn:
            await conn.execute(text(_insert_order_sql("ORD-GROUND-2", 1299.0)))
        return await ApprovalGatekeeper.evaluate_refund_auto_approval("ORD-GROUND-2", None, 100)

    out = asyncio.run(_scenario())
    assert out["shouldAutoApprove"] is False and out["groundedAmount"] == 1299.0


def test_missing_order_fails_closed(pg_factory):
    """查无此单(幽灵单)→ 无快照可回照 → fail-closed,不放行。"""
    out = asyncio.run(ApprovalGatekeeper.evaluate_refund_auto_approval("ORD-GHOST", None, 100))
    assert out["shouldAutoApprove"] is False and out["groundedAmount"] == _FAIL_CLOSED_AMOUNT


# ---------- 相邻红线:高价值地址变更(evaluate_address_change_policy) ----------


def _insert_order_with_status(order_id: str, status: str, total: float) -> str:
    return (
        "INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery, "
        f"business_id, total_amount) VALUES ('{order_id}', '{status}', 'sf', 'SF001', '3天', "
        f"'ecommerce', {total})"
    )


def test_high_value_unshipped_address_change_flagged(pg_factory):
    """未发货 + >100 → 高价值红线,改址必须过 HITL。"""

    async def _scenario():
        engine = pg_factory.kw["bind"]
        async with engine.begin() as conn:
            await conn.execute(text(_insert_order_with_status("ORD-ADDR-1", "processing", 1299.0)))
        return await ApprovalGatekeeper.evaluate_address_change_policy("ORD-ADDR-1")

    out = asyncio.run(_scenario())
    assert out == {"isHighValue": True, "totalAmount": 1299.0}


def test_shipped_order_not_flagged(pg_factory):
    """已发货订单改址另有物流拦截语义,不高价值红线。"""

    async def _scenario():
        engine = pg_factory.kw["bind"]
        async with engine.begin() as conn:
            await conn.execute(text(_insert_order_with_status("ORD-ADDR-2", "shipped", 1299.0)))
        return await ApprovalGatekeeper.evaluate_address_change_policy("ORD-ADDR-2")

    out = asyncio.run(_scenario())
    assert out["isHighValue"] is False


def test_low_value_address_change_not_flagged(pg_factory):
    async def _scenario():
        engine = pg_factory.kw["bind"]
        async with engine.begin() as conn:
            await conn.execute(text(_insert_order_with_status("ORD-ADDR-3", "processing", 50.0)))
        return await ApprovalGatekeeper.evaluate_address_change_policy("ORD-ADDR-3")

    out = asyncio.run(_scenario())
    assert out["isHighValue"] is False


def test_address_policy_without_order_is_honest_low():
    out = asyncio.run(ApprovalGatekeeper.evaluate_address_change_policy(None))
    assert out == {"isHighValue": False, "totalAmount": 0}
