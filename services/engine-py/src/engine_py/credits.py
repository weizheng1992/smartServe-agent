"""商户积分池账户与台账(2026-10-21 用量配额闸,spec .scratch/agent-usage-quota)。

余额唯一真相在 merchant_credit_accounts:一切增减走带守卫的单语句原子
UPDATE(不可能扣穿零),credit_transactions 只追加审计台账。懒初始化:首个
触达方 INSERT ON CONFLICT DO NOTHING 赠 AI_MERCHANT_INITIAL_CREDITS 并同
事务落 initial_grant。

依赖方向:本模块属 engine,gateway_py/quota.py(回合闸)与 billing 路由
(admin 调整/查询)下行导入;run_agent 结算线(首帧前技术失败退回)同侧
直调。与既有 token 观测面(tenant_billing_quotas/session_metrics)互不干涉。
"""

from __future__ import annotations

import os

from sqlalchemy import desc, select, text
from sqlalchemy.exc import IntegrityError

from .db import CreditTransaction, MerchantCreditAccount, get_session

REASON_INITIAL_GRANT = "initial_grant"
REASON_CONSUME = "consume"
REASON_REFUND = "refund"
REASON_ADMIN_ADJUST = "admin_adjust"


def initial_credits() -> int:
    return int(os.environ.get("AI_MERCHANT_INITIAL_CREDITS", "1000"))


async def _ensure_account(session, business_id: str) -> None:
    """懒初始化(幂等):首次触达赠初始额,同事务落 initial_grant 台账。"""
    grant = initial_credits()
    result = await session.execute(
        text(
            "INSERT INTO merchant_credit_accounts (business_id, balance) "
            "VALUES (:b, :init) ON CONFLICT (business_id) DO NOTHING"
        ).bindparams(b=business_id, init=grant)
    )
    if result.rowcount == 1:
        session.add(CreditTransaction(business_id=business_id, delta=grant, reason=REASON_INITIAL_GRANT))


async def consume_credit(business_id: str, *, job_id: str) -> bool:
    """原子扣 1(余额守卫,rowcount=0 即池尽 False);成功落 consume 台账。"""
    async with get_session() as session:
        await _ensure_account(session, business_id)
        result = await session.execute(
            text(
                "UPDATE merchant_credit_accounts SET balance = balance - 1, updated_at = now() "
                "WHERE business_id = :b AND balance >= 1"
            ).bindparams(b=business_id)
        )
        if result.rowcount == 0:
            await session.rollback()
            return False
        session.add(
            CreditTransaction(business_id=business_id, delta=-1, reason=REASON_CONSUME, ref_job_id=job_id)
        )
        await session.commit()
        return True


async def refund_credit(business_id: str, *, job_id: str) -> bool:
    """技术失败退回 +1;refund 部分唯一索引(ref_job_id)挡双退,重入幂等 False。

    两道守卫闭合「余额唯一真相」律:
    - 扣费在案才许退(job_resume_* 恢复轮经引擎侧直派、从未过闸扣费,其技术
      失败退回 False——否则无 consume 对应行的 +1 让台账归因漂移);
    - rowcount 守卫:账户行不存在时 0 行 UPDATE 不得落孤立台账。"""
    async with get_session() as session:
        consume_in_ledger = (
            await session.execute(
                select(CreditTransaction.id)
                .where(
                    CreditTransaction.business_id == business_id,
                    CreditTransaction.ref_job_id == job_id,
                    CreditTransaction.reason == REASON_CONSUME,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if consume_in_ledger is None:
            return False
        session.add(
            CreditTransaction(business_id=business_id, delta=1, reason=REASON_REFUND, ref_job_id=job_id)
        )
        try:
            # autoflush 先落台账行,唯一索引在下一句 UPDATE 前即拦重入
            result = await session.execute(
                text(
                    "UPDATE merchant_credit_accounts SET balance = balance + 1, updated_at = now() "
                    "WHERE business_id = :b"
                ).bindparams(b=business_id)
            )
            if result.rowcount == 0:
                await session.rollback()
                return False
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def adjust_credit(business_id: str, delta: int, *, reason: str, operator: str | None = None) -> bool:
    """管理调整(充值正/核减负,operator 记平台管理员);负向带余额守卫防穿零。"""
    async with get_session() as session:
        await _ensure_account(session, business_id)
        if delta >= 0:
            result = await session.execute(
                text(
                    "UPDATE merchant_credit_accounts SET balance = balance + :d, updated_at = now() "
                    "WHERE business_id = :b"
                ).bindparams(b=business_id, d=delta)
            )
        else:
            result = await session.execute(
                text(
                    "UPDATE merchant_credit_accounts SET balance = balance + :d, updated_at = now() "
                    "WHERE business_id = :b AND balance >= :need"
                ).bindparams(b=business_id, d=delta, need=-delta)
            )
        if result.rowcount == 0:
            await session.rollback()
            return False
        session.add(
            CreditTransaction(business_id=business_id, delta=delta, reason=reason, operator=operator)
        )
        await session.commit()
        return True


async def get_balance(business_id: str) -> int | None:
    """余额快照;未初始化(无账户行)诚实 None,不编造 0。"""
    async with get_session() as session:
        row = (
            await session.execute(
                select(MerchantCreditAccount).where(MerchantCreditAccount.business_id == business_id)
            )
        ).scalar_one_or_none()
        return row.balance if row else None


async def recent_transactions(business_id: str, limit: int = 20) -> list[dict]:
    """最近流水(新→旧);camelCase 直出前端契约。"""
    async with get_session() as session:
        rows = (
            (
                await session.execute(
                    select(CreditTransaction)
                    .where(CreditTransaction.business_id == business_id)
                    .order_by(desc(CreditTransaction.created_at))
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": str(r.id),
                "delta": r.delta,
                "reason": r.reason,
                "refJobId": r.ref_job_id,
                "operator": r.operator,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
