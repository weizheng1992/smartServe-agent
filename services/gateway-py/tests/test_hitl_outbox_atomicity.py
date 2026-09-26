"""事务发件箱原子性钉死(架构不变量 #3;2026-09-26 夜审 ④ 测试补强)。

审批裁决的工单状态变更与 approval_outbox_events 事件必须在同一事务原子
提交 —— 注入「事件写入失败」后,裁决必须整体回滚:工单不得单侧翻转为
approved/rejected 而事件蒸发(事件蒸发 = 恢复派发永不发生,顾客侧永久
挂起等待一个不会到来的续跑)。
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded")


async def _insert_waiting_ticket(approval_id: str) -> str:
    from engine_py.db import get_session

    tid = f"hitl_atomic_thread_{_TS}"
    await create_thread(tid, "u_hitl_atomic", "nike")
    async with get_session() as session:
        await session.execute(
            sa.text(
                "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, 'nike', 'waiting', 'processRefund', "
                "'发件箱原子性工单', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(id=approval_id, tid=tid)
        )
        await session.commit()
    return tid


async def _ticket_status(approval_id: str) -> str | None:
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                sa.text("SELECT status FROM pending_approvals WHERE id = CAST(:aid AS uuid)").bindparams(aid=approval_id)
            )
        ).first()
    return row[0] if row else None


async def _outbox_count(approval_id: str) -> int:
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                sa.text("SELECT COUNT(*) FROM approval_outbox_events WHERE approval_id = :aid").bindparams(
                    aid=approval_id
                )
            )
        ).first()
    return int(row[0]) if row else 0


class TestOutboxAtomicity:
    async def test_event_write_failure_rolls_back_status_change(self, client, monkeypatch):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)

        from engine_py.approvals import gatekeeper

        class _OutboxDown:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("outbox unavailable")

        monkeypatch.setattr(gatekeeper, "ApprovalOutboxEvent", _OutboxDown)

        res = await client.post(
            "/api/admin/approvals",
            json={"approvalId": aid, "action": "approve", "actor": "merchant_operator"},
        )
        assert res.status_code == 500, res.text
        assert res.json().get("success") is not True

        assert await _ticket_status(aid) == "waiting", "事件写入失败时工单状态必须回滚为 waiting"
        assert await _outbox_count(aid) == 0

    async def test_happy_path_writes_status_and_event_together(self, client):
        """对照组:正常裁决两写同现(与 test_approval_lifecycle_gateway 呼应)。"""
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)

        res = await client.post(
            "/api/admin/approvals",
            json={"approvalId": aid, "action": "approve", "actor": "merchant_operator"},
        )
        assert res.status_code == 200, res.text

        assert await _ticket_status(aid) == "approved"
        assert await _outbox_count(aid) == 1
