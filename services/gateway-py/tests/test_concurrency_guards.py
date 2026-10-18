"""并发守卫回归(2026-10-18:async-2 认领竞态 / async-3 地址簿丢写 / critic#5 seed 环境闸)。

- create_thread 无主线程自愈认领:条件 UPDATE(user_id IS NULL)+rowcount,
  两并发认领恰好一人成功,败者 None(路由层 409 不回显)—— 旧无谓词 UPDATE
  后写覆写夺主且败者已收 success;
- save_customer_address:取货/合并/覆写同事务 + 每客户咨询锁,并发各存一条
  地址两条都留 —— 旧「独立 connect 读整组 + 另一 begin 整列覆写」后写必丢先写;
- seed_merchant_data:MERCHANT_SEED_ALLOW 未显式开启拒绝执行(清空重插商户
  真账库,误跑即污染销量聚合)。
"""

from __future__ import annotations

import asyncio
import uuid as _uuid

import pytest
from engine_py.db import get_session
from sqlalchemy import text

from gateway_py.conversation_repo import create_thread
from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine
from gateway_py.merchant_domain import get_customer_addresses, save_customer_address
from gateway_py.merchant_seed import seed_merchant_data

from .conftest import _TS


def _tid(tag: str) -> str:
    return f"cguard_{tag}_{_TS}_{_uuid.uuid4().hex[:6]}"


async def _del_threads(*tids: str) -> None:
    async with get_session() as session:
        for tid in tids:
            await session.execute(text("DELETE FROM messages WHERE thread_id = :t").bindparams(t=tid))
            await session.execute(text("DELETE FROM threads WHERE id = :t").bindparams(t=tid))
        await session.commit()


async def _del_customer(cid: str) -> None:
    # merchant_customers 在商户真账库(agent_merchant),走 merchant_engine 而非
    # 平台库 get_session —— 两个库两套连接,清错库 = 表不存在
    await ensure_merchant_tables()
    async with merchant_engine().begin() as conn:
        await conn.execute(
            text("DELETE FROM merchant_customers WHERE customer_id = :c").bindparams(c=cid)
        )


async def test_ownerless_thread_concurrent_claim_single_winner(contract_fixtures):
    tid = _tid("claim")
    await create_thread(tid, "nike", None)  # 无主线程(dispatch 自愈建线程形状;签名 tid, biz, uid)
    try:
        first, second = await asyncio.gather(
            create_thread(tid, "nike", "u_claim_a"),
            create_thread(tid, "nike", "u_claim_b"),
        )
        winners = [r for r in (first, second) if r is not None]
        assert len(winners) == 1, f"两并发认领必须恰一人成功,败者 None(409): {first} / {second}"
        assert winners[0]["userId"] in {"u_claim_a", "u_claim_b"}

        # 终态:属主为胜者,且第三人再认领 → None(已有属主)
        third = await create_thread(tid, "nike", "u_claim_c")
        assert third is None
    finally:
        await _del_threads(tid)


async def test_address_concurrent_saves_keep_both(contract_fixtures):
    cid = f"CUST-CT-ADDR-{_uuid.uuid4().hex[:8]}"
    try:
        first, second = await asyncio.gather(
            save_customer_address(
                cid, {"recipientName": "甲", "phone": "13800000001", "fullAddress": "并发测试地址甲"}
            ),
            save_customer_address(
                cid, {"recipientName": "乙", "phone": "13800000002", "fullAddress": "并发测试地址乙"}
            ),
        )
        assert first["success"] is True and second["success"] is True

        addresses = await get_customer_addresses(cid)
        fulls = {a.get("fullAddress") for a in addresses}
        assert {"并发测试地址甲", "并发测试地址乙"} <= fulls, (
            f"并发各存一条必须两条都留(旧整列覆写必丢一条): {addresses}"
        )
        # 默认位唯一:恰一条 isDefault
        defaults = [a for a in addresses if a.get("isDefault")]
        assert len(defaults) == 1
    finally:
        await _del_customer(cid)


async def test_seed_requires_explicit_optin(monkeypatch):
    monkeypatch.delenv("MERCHANT_SEED_ALLOW", raising=False)
    with pytest.raises(RuntimeError, match="MERCHANT_SEED_ALLOW"):
        await seed_merchant_data()
