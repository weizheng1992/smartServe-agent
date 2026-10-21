"""credits 积分账本单元册(2026-10-21 用量配额闸,票 01/04)。

钉面:懒初始化 initial_grant / 消扣余额守卫(不穿零)/ refund 部分唯一索引
挡双退(重入幂等 False)/ adjust 负向守卫。经 pg_factory 密封 PG(NullPool +
每测独立事件循环,模块级会话工厂整体替换)。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from engine_py import credits

pytestmark = pytest.mark.usefixtures("pg_factory")


def _biz() -> str:
    return f"cred_{uuid.uuid4().hex[:10]}"


def test_consume_lazy_init_and_zero_guard():
    biz = _biz()

    async def run():
        # 未触达前诚实 None(不编造 0)
        assert await credits.get_balance(biz) is None
        assert await credits.consume_credit(biz, job_id="j1") is True
        assert await credits.get_balance(biz) == credits.initial_credits() - 1
        # 排干后守卫拒绝,余额钉在 0
        while await credits.consume_credit(biz, job_id="jd"):
            pass
        assert await credits.get_balance(biz) == 0
        assert await credits.consume_credit(biz, job_id="jx") is False
        assert await credits.get_balance(biz) == 0

    asyncio.run(run())


def test_refund_once_then_idempotent():
    biz = _biz()

    async def run():
        assert await credits.consume_credit(biz, job_id="j1") is True
        before = await credits.get_balance(biz)
        assert await credits.refund_credit(biz, job_id="j1") is True
        assert await credits.get_balance(biz) == before + 1
        # 同 job 双退被 refund 部分唯一索引挡下(幂等 False,余额不动)
        assert await credits.refund_credit(biz, job_id="j1") is False
        assert await credits.get_balance(biz) == before + 1

    asyncio.run(run())


def test_refund_job_id_scoped_per_business():
    """回归钉面(0024 首版实测):refund 唯一索引是 (business_id, ref_job_id)
    复合 —— 只含 ref_job_id 时跨商户同 job id 会误撞唯一索引,他商户退回被吞。"""
    biz_a, biz_b = _biz(), _biz()

    async def run():
        await credits.consume_credit(biz_a, job_id="shared_job")
        await credits.consume_credit(biz_b, job_id="shared_job")
        assert await credits.refund_credit(biz_a, job_id="shared_job") is True
        assert await credits.refund_credit(biz_b, job_id="shared_job") is True
        assert await credits.get_balance(biz_a) == await credits.get_balance(biz_b)

    asyncio.run(run())


def test_adjust_positive_and_negative_guard():
    biz = _biz()

    async def run():
        assert await credits.adjust_credit(biz, 500, reason="充值", operator="p@aurora") is True
        assert await credits.get_balance(biz) == credits.initial_credits() + 500
        assert await credits.adjust_credit(biz, -10_000_000, reason="超额核减") is False
        assert await credits.get_balance(biz) == credits.initial_credits() + 500
        assert await credits.adjust_credit(biz, -200, reason="核减", operator="p@aurora") is True
        assert await credits.get_balance(biz) == credits.initial_credits() + 300

    asyncio.run(run())


def test_refund_missing_account_guarded():
    """评审修复回归:账户行不存在时退回 0 行 UPDATE 不得落孤立台账
    (否则 Σdelta ≠ balance 永久漂移)。"""
    biz = _biz()

    async def run():
        assert await credits.refund_credit(biz, job_id="j_ghost") is False
        assert await credits.get_balance(biz) is None
        assert await credits.recent_transactions(biz) == []

    asyncio.run(run())


def test_ledger_records_all_reasons():
    biz = _biz()

    async def run():
        await credits.consume_credit(biz, job_id="j1")
        assert await credits.refund_credit(biz, job_id="j1") is True
        await credits.adjust_credit(biz, 5, reason="admin_adjust: 充值", operator="p@aurora")
        rows = await credits.recent_transactions(biz, limit=10)
        reasons = [r["reason"] for r in rows]
        assert "initial_grant" in reasons and "consume" in reasons
        assert "refund" in reasons
        assert any(r.startswith("admin_adjust") for r in reasons)
        consume_row = next(r for r in rows if r["reason"] == "consume")
        assert consume_row["refJobId"] == "j1" and consume_row["delta"] == -1
        # tz-aware(两套钟收口律):台账 isoformat 必须带时区,naive 串会被前端
        # new Date 按本地钟解析(下单时间早 8 小时同款事故)
        assert rows[0]["createdAt"] and ("+" in rows[0]["createdAt"] or rows[0]["createdAt"].endswith("Z"))

    asyncio.run(run())
