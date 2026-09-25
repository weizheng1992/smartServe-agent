"""审批生命周期契约(2026-09-25 夜审测试缺口 Top-2;agent 链路优先)。

夜审钉死的缺口:网关审批单此前只钉了 approve 单点
(test_resolve_fixture_approval / actor 契约),驳回/取消/重复提交三条
终局路径与事务发件箱事件体零覆盖 —— 而 HITL fail-closed 修复
(gatekeeper 异常回 "error" 态)正依赖这些路径的行为不变性。

钉死四事:
1. reject → status=rejected + 发件箱 reject_execution 事件,payload 带
   确定性 jobId job_resume_{approvalId} 与驳回原因;
2. 同单重复提交 → 400「已经处理过」(终局态不可二次执行,防重复退款);
3. cancel → status=cancelled + cancel_execution 事件;
4. approve(processRefund 单)→ resume_execution 事件 + 确定性 jobId。
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded")

_TICKET_DDL = (
    "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
    "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, 'nike', 'waiting', :atype, "
    "'生命周期契约工单', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') ON CONFLICT (id) DO NOTHING"
)


async def _insert_waiting_ticket(ticket_id: str, action_type: str = "processRefund") -> None:
    from engine_py.db import get_session

    tid = f"lifecycle_thread_{_TS}"
    await create_thread(tid, "u_lifecycle", "nike")
    async with get_session() as session:
        await session.execute(
            sa.text(_TICKET_DDL).bindparams(id=ticket_id, tid=tid, atype=action_type)
        )
        await session.commit()


async def _outbox_events(approval_id: str) -> list[sa.Row]:
    from engine_py.db import get_session

    async with get_session() as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT event_type, payload FROM approval_outbox_events "
                    "WHERE approval_id = :aid ORDER BY created_at"
                ).bindparams(aid=approval_id)
            )
        ).mappings().all()
    return rows


async def _resolve(client, approval_id: str, action: str, **extra) -> dict:
    res = await client.post(
        "/api/approvals",
        headers={"x-tenant-id": "nike"},
        json={"approvalId": approval_id, "action": action, **extra},
    )
    assert res.status_code == 200, res.text
    return res.json()


class TestApprovalLifecycle:
    async def test_reject_writes_outbox_event_and_replays_are_blocked(self, client):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)

        body = await _resolve(client, aid, "reject", rejectionReason="凭证不足不予退款")
        assert body["status"] == "rejected"
        assert body["jobId"] == f"job_resume_{aid}"

        events = await _outbox_events(aid)
        assert len(events) == 1
        assert events[0]["event_type"] == "reject_execution"
        payload = events[0]["payload"]
        assert payload["jobId"] == f"job_resume_{aid}"
        assert payload["nextStatus"] == "rejected"

        # 终局态重放:严禁二次执行(fail-closed 闸的同源防线)。
        # 冻结契约:业务错误不翻 HTTP 状态码,200 + body{error, statusCode:400},
        # 前端按 success/error 字段呈现(fetchJson 通道)。
        res = await client.post(
            "/api/approvals",
            headers={"x-tenant-id": "nike"},
            json={"approvalId": aid, "action": "reject"},
        )
        assert res.status_code == 200
        body2 = res.json()
        assert body2["statusCode"] == 400
        assert "已经处理过" in body2["error"]
        assert body2["error"].endswith("rejected")

    async def test_cancel_writes_cancel_event(self, client):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)

        body = await _resolve(client, aid, "cancel")
        assert body["status"] == "cancelled"

        events = await _outbox_events(aid)
        assert [e["event_type"] for e in events] == ["cancel_execution"]
        assert events[0]["payload"]["nextStatus"] == "cancelled"

    async def test_approve_refund_ticket_resumes_with_deterministic_job(self, client):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid, action_type="processRefund")

        body = await _resolve(client, aid, "approve")
        assert body["status"] == "approved"
        assert body["jobId"] == f"job_resume_{aid}"

        events = await _outbox_events(aid)
        assert [e["event_type"] for e in events] == ["resume_execution"]
        assert events[0]["payload"]["jobId"] == f"job_resume_{aid}"
