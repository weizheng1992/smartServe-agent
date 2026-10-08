"""SPI 通道审批裁决契约(POST /api/v1/spi/approvals/{id}/resolve)。

夜审实查:SPI 通道此前漏注入 resolvedBy/resolvedByRole(gatekeeper 兜底落
「unknown」),且 `"humanReply": body.get("reviewerId") and None` 恒 None ——
与商户路由已修的「审批人落库 unknown」(工单 04 审计)同款漂移。钉死六事:

1. SPI reject 携 reviewerId → 外部操作者身份落 pending_approvals.action_payload;
2. 未带操作者 → 以 AGENT_SPI/system 声明机器通道身份,不再 unknown;
3. human_reply 带 replyMessage → 人工回复直通(不再被恒 None 吞掉);
4. 缺 x-tenant-id 头 → 400(架构审查 #2:三方通道此前连归属校验都没有);
5. 工单归属他租 vs 租户头 → 403 且工单原地不动(全局 key 不得跨租户核销);
6. 未知动作 → 400 诚实失败(不再落引擎按驳回语义静默错误终局)。
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded")

_SPI_HEADERS = {"x-api-key": "test_spi_key", "x-tenant-id": "nike"}


async def _insert_waiting_ticket(ticket_id: str) -> str:
    from engine_py.db import get_session

    tid = f"spi_resolve_thread_{_TS}"
    await create_thread(tid, "u_spi_resolve", "nike")
    async with get_session() as session:
        await session.execute(
            sa.text(
                "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, 'nike', 'waiting', 'processRefund', "
                "'SPI 裁决契约工单', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(id=ticket_id, tid=tid)
        )
        await session.commit()
    return tid


async def _outbox_payloads(approval_id: str) -> list[dict]:
    from engine_py.db import get_session

    async with get_session() as session:
        rows = (
            await session.execute(
                sa.text(
                    "SELECT payload FROM approval_outbox_events WHERE approval_id = :aid ORDER BY created_at"
                ).bindparams(aid=approval_id)
            )
        ).mappings().all()
    return [dict(r["payload"]) for r in rows]


async def _approval_action_payload(approval_id: str) -> dict:
    """核准人身份落 pending_approvals.action_payload(事件体只带 jobId/状态,不带 actor)。"""
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                sa.text("SELECT action_payload FROM pending_approvals WHERE id = CAST(:aid AS uuid)").bindparams(
                    aid=approval_id
                )
            )
        ).mappings().first()
    return dict(row["action_payload"] or {})


class TestSpiApprovalResolve:
    async def test_reject_records_external_reviewer_identity(self, client):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)
        res = await client.post(
            f"/api/v1/spi/approvals/{aid}/resolve",
            headers=_SPI_HEADERS,
            json={"action": "reject", "rejectionReason": "外部风控驳回", "reviewerId": "ext_platform_ops"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "rejected"
        assert body["jobId"] == f"job_resume_{aid}"
        payloads = await _outbox_payloads(aid)
        assert payloads, "驳回必须写发件箱事件"
        stored = await _approval_action_payload(aid)
        assert stored.get("resolvedBy") == "ext_platform_ops"
        assert stored.get("resolvedByRole") == "merchant_operator"
        assert stored.get("rejectionReason") == "外部风控驳回"

    async def test_missing_reviewer_falls_back_to_agent_spi_not_unknown(self, client):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)
        res = await client.post(
            f"/api/v1/spi/approvals/{aid}/resolve",
            headers=_SPI_HEADERS,
            json={"action": "reject", "rejectionReason": "未带操作者"},
        )
        assert res.status_code == 200, res.text
        stored = await _approval_action_payload(aid)
        assert stored.get("resolvedBy") == "AGENT_SPI"
        assert stored.get("resolvedByRole") == "system"

    async def test_human_reply_is_forwarded_not_swallowed(self, client):
        aid = str(uuid.uuid4())
        tid = await _insert_waiting_ticket(aid)
        res = await client.post(
            f"/api/v1/spi/approvals/{aid}/resolve",
            headers=_SPI_HEADERS,
            json={"action": "human_reply", "replyMessage": "人工客服已介入处理", "isFinish": False},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body.get("success") is True
        assert body.get("isHumanActive") is True
        assert body.get("threadId") == tid

    async def test_missing_tenant_header_is_400(self, client):
        """架构审查 #2:归属闸前置 —— 租户头必带,与 escalation 双路由同闸。"""
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)
        res = await client.post(
            f"/api/v1/spi/approvals/{aid}/resolve",
            headers={"x-api-key": "test_spi_key"},
            json={"action": "reject", "rejectionReason": "无租户头"},
        )
        assert res.status_code == 400
        assert "x-tenant-id" in res.json()["detail"]

    async def test_cross_tenant_ticket_is_403_and_untouched(self, client):
        """架构审查 #2:全局 key 声明 aurora 头,不得核销 nike 的工单。"""
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)  # business_id='nike'
        res = await client.post(
            f"/api/v1/spi/approvals/{aid}/resolve",
            headers={"x-api-key": "test_spi_key", "x-tenant-id": "aurora"},
            json={"action": "reject", "rejectionReason": "跨租户核销"},
        )
        assert res.status_code == 403, res.text
        assert "不属于" in res.json()["error"]
        # 工单原地不动:仍是 waiting,零发件箱事件
        from engine_py.db import get_session

        async with get_session() as session:
            status = (
                await session.execute(
                    sa.text("SELECT status FROM pending_approvals WHERE id = CAST(:aid AS uuid)").bindparams(aid=aid)
                )
            ).scalar_one()
        assert status == "waiting"
        assert await _outbox_payloads(aid) == []

    async def test_unknown_action_is_honest_400(self, client):
        """架构审查 #2:未知动作 400,不再落引擎按驳回语义静默错误终局。"""
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)
        res = await client.post(
            f"/api/v1/spi/approvals/{aid}/resolve",
            headers=_SPI_HEADERS,
            json={"action": "self_approve_forever", "rejectionReason": "越权动作"},
        )
        assert res.status_code == 400
        assert "未知审批动作" in res.json()["detail"]
