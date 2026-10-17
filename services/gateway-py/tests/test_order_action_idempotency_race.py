"""订单动作幂等竞态回归(async-4,2026-10-17):旧「查后插」下同 key 并发
双请求都能通过预检,败者撞 merchant_audit_logs.idempotency_key 唯一约束
IntegrityError → store_spi 兜底 500 —— 重放非幂等。

修复:审计 INSERT 改 ON CONFLICT (idempotency_key) DO NOTHING RETURNING ——
唯一约束即幂等闸;并发败者回读胜者行抛 _IdempotentReplay,自身变更随事务
整体回滚(与旧 IntegrityError 回滚语义一致),回放胜者结果(200)。

断言纪律:无论调度交叠落在哪种时序(串行/交错/锁等待),四个恒真断言:
恰好一行审计、订单终态唯一、两呼皆 success True、两呼共享胜者 refundId。
"""

from __future__ import annotations

import asyncio
import uuid as _uuid

import pytest
from sqlalchemy import text

from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine
from gateway_py.merchant_domain import _audit_insert_idempotent, _IdempotentReplay, execute_order_action
from tests.merchant_seed_helpers import seed_merchant_order

_UID = "CUST-CT-IDEM-A"
_OID = "CT-IDEM-ORD-1"


def _key() -> str:
    return f"CT-IDEM-{_uuid.uuid4().hex[:12]}"


async def _cleanup(keys: list[str]) -> None:
    async with merchant_engine().begin() as conn:
        for k in keys:
            await conn.execute(
                text("DELETE FROM merchant_audit_logs WHERE idempotency_key = :k").bindparams(k=k)
            )
        await conn.execute(text("DELETE FROM merchant_orders WHERE order_id = :o").bindparams(o=_OID))


async def test_audit_insert_conflict_raises_replay_with_winner_row(client, contract_fixtures):
    """确定性打 _IdempotentReplay 分支:胜者行同事务已插 → helper 必撞唯一
    约束,异常携带胜者行(id + JSONB result 回读为 dict)。"""
    await ensure_merchant_tables()
    key = _key()
    try:
        async with merchant_engine().begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO merchant_audit_logs (action_type, order_id, idempotency_key, operator, payload, result) "
                    "VALUES ('REQUEST_REFUND', :o, :k, 'AGENT_SPI', "
                    "CAST('{}' AS jsonb), CAST('{\"refundId\": \"RF_WINNER\"}' AS jsonb)) "
                    "ON CONFLICT (idempotency_key) DO NOTHING"
                ).bindparams(o=_OID, k=key)
            )
            with pytest.raises(_IdempotentReplay) as ei:
                await _audit_insert_idempotent(
                    conn,
                    action_type="REQUEST_REFUND",
                    order_id=_OID,
                    idempotency_key=key,
                    payload_json="{}",
                    result_json="{}",
                )
        assert ei.value.log_row.get("id") is not None
        assert ei.value.log_row.get("result") == {"refundId": "RF_WINNER"}, "JSONB 胜者结果须回读为 dict"
    finally:
        await _cleanup([key])


async def test_concurrent_same_key_refund_settles_once_and_replays(client, contract_fixtures):
    """真并发双呼(asyncio.gather):终局唯一 —— 恰一行审计、订单 REFUNDED、
    两呼皆 success True 且共享胜者 refundId、至少一呼为幂等重放(200 非 500)。"""
    await ensure_merchant_tables()
    key = _key()
    try:
        async with merchant_engine().begin() as conn:
            await seed_merchant_order(conn, order_id=_OID, customer_id=_UID, total_amount=199.0)

        req = {"actionType": "REQUEST_REFUND", "orderId": _OID, "idempotencyKey": key, "refundAmount": 199.0}
        first, second = await asyncio.gather(
            execute_order_action(dict(req)),
            execute_order_action(dict(req)),
        )
        results = [first, second]
        assert all(r["success"] is True for r in results), f"两呼(含并发败者)都必须 200 成功: {results}"
        refund_ids = {r.get("refundId") for r in results}
        assert len(refund_ids) == 1, f"两呼必须共享胜者退款单,严禁双退款单: {results}"
        assert any("幂等防重响应" in (r.get("message") or "") for r in results), "至少一呼为幂等重放"

        async with merchant_engine().connect() as conn:
            audit_rows = (
                await conn.execute(
                    text("SELECT id FROM merchant_audit_logs WHERE idempotency_key = :k").bindparams(k=key)
                )
            ).all()
            status = (
                await conn.execute(
                    text("SELECT status FROM merchant_orders WHERE order_id = :o").bindparams(o=_OID)
                )
            ).scalar()
        assert len(audit_rows) == 1, "恰好一行审计(唯一约束即幂等闸)"
        assert status == "REFUNDED"
    finally:
        await _cleanup([key])
