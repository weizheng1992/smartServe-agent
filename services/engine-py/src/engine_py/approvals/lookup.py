"""审批单查询 — ApprovalGatekeeper 的只读子集(planner 热恢复/驳回回溯依赖)。

完整 Gatekeeper(挂起创建、outbox 原子提交、审批动作处理)随 executor/HITL 批次移植,
本模块先提供 planner 所需的两个查询,键名保持 TS camelCase(PendingApprovalRecord)。
"""

from __future__ import annotations

from sqlalchemy import select

from ..db import PendingApproval, get_session


def _to_record(row: PendingApproval) -> dict:
    return {
        "id": str(row.id),
        "threadId": row.thread_id,
        "businessId": row.business_id,
        "actionType": row.action_type,
        "actionPayload": row.action_payload or {},
        "status": row.status or "waiting",
        "reason": row.reason,
        "deadline": row.deadline.isoformat() if row.deadline else None,
    }


async def find_approval_by_id(approval_id: str) -> dict | None:
    async with get_session() as session:
        row = (
            await session.execute(
                select(PendingApproval).where(PendingApproval.id == approval_id).limit(1)
            )
        ).scalar_one_or_none()
        return _to_record(row) if row else None


async def find_latest_approval_by_thread_id(thread_id: str) -> dict | None:
    async with get_session() as session:
        row = (
            await session.execute(
                select(PendingApproval)
                .where(PendingApproval.thread_id == thread_id)
                .order_by(PendingApproval.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return _to_record(row) if row else None
