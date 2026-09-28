"""live-desk-rework P4 契约(spec §2.6/§2.7):工单联动与消息可靠性。

钉死四件事:
1. human_reply 退役 —— 双路径(/api/approvals、/api/chat/approvals)白名单
   移除后 400「未知审批动作」;human_finish 留 P5(禁区 useApprovalMachine 配合)。
2. 台内一等批驳 —— 员工代行 approve/reject 走 /api/chat/approvals 须持
   live_desk:approve(rbac 种子新权限点);无权限员工 403;顾客通道(userId
   归属绑定)不受此闸。
3. 批驳后不自动释放 —— escalation 工单 reject 只落 rejected 终局,不发
   「服务已结束」系统消息、不清 assigned_operator_id、threads 保持
   human_takeover(此前 reject 误落 human_finish 分支被连带释放)。
4. clientMsgId 消息幂等 —— socket send_message 透传客户端 id 为消息主键,
   重放 ON CONFLICT 静默:两次 ack 同 messageId、时间线仅一行、unread 只 +1;
   非法 clientMsgId 忽略回落服务端 uuid4。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded")

_P4_THREAD = f"p4_decouple_{_TS}"
_P4_USER = "u_p4_owner"
_ESC_THREAD = f"p4_esc_{_TS}"
_OP_EMAIL = "op_p4@aurora.test"


async def _insert_escalation_ticket(ticket_id: str, thread_id: str, tenant: str = "aurora") -> None:
    """升级工单(顾客呼叫人工产生):waiting + action_type=human_escalation。"""
    from engine_py.db import get_session

    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, :bid, 'waiting', 'human_escalation', "
                "'顾客呼叫人工', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(id=ticket_id, tid=thread_id, bid=tenant)
        )
        await session.commit()


async def _set_takeover(thread_id: str, operator: str = "op_p4_duty") -> None:
    from engine_py.db import get_session

    async with get_session() as session:
        await session.execute(
            text(
                "UPDATE threads SET status = 'human_takeover', assigned_operator_id = :op WHERE id = :tid"
            ).bindparams(op=operator, tid=thread_id)
        )
        await session.commit()


async def _thread_row(thread_id: str) -> dict:
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                text(
                    'SELECT status, assigned_operator_id AS "op" FROM threads WHERE id = :tid'
                ).bindparams(tid=thread_id)
            )
        ).mappings().one_or_none()
    return dict(row) if row else {}


async def _approval_status(ticket_id: str) -> str | None:
    from engine_py.db import get_session

    async with get_session() as session:
        return (
            await session.execute(
                text("SELECT status FROM pending_approvals WHERE id = CAST(:id AS uuid)").bindparams(id=ticket_id)
            )
        ).scalar_one_or_none()


async def _message_count(thread_id: str, needle: str) -> int:
    from engine_py.db import get_session

    async with get_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM messages WHERE thread_id = :tid AND content LIKE :pat"
                ).bindparams(tid=thread_id, pat=f"%{needle}%")
            )
        ).scalar_one()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def esc_thread(seeded, staff_auth):
    """升级工单场景:接管中会话 + 坐席在岗 + waiting escalation 工单。"""
    from engine_py.analytics import rbac

    await rbac.ensure_menu_seed("aurora")  # 幂等补 btn-live-desk-approve 种子
    await create_thread(_ESC_THREAD, _P4_USER, "aurora")
    await _set_takeover(_ESC_THREAD)
    aid = str(uuid.uuid4())
    await _insert_escalation_ticket(aid, _ESC_THREAD)
    return {"approvalId": aid}


class TestHumanReplyRetired:
    async def test_human_reply_via_chat_path_400(self, client, staff_auth):
        res = await client.post(
            "/api/chat/approvals",
            headers=staff_auth,
            json={"approvalId": str(uuid.uuid4()), "action": "human_reply", "humanReply": "您好", "isFinish": False},
        )
        assert res.status_code == 400, res.text
        assert "未知审批动作" in res.json()["detail"]

    async def test_human_reply_via_plain_path_400(self, client):
        res = await client.post(
            "/api/approvals",
            headers={"x-user-id": _P4_USER},
            json={"approvalId": str(uuid.uuid4()), "action": "human_reply", "replyMessage": "您好"},
        )
        assert res.status_code == 400
        assert "未知审批动作" in res.json()["detail"]

    async def test_human_finish_still_accepted_auth_layer(self, client, staff_auth):
        """human_finish 未退役(P5 与 useApprovalMachine 禁区配合同批收):
        过白名单进引擎语义(查无工单 → 引擎 404 信封),不落本面 400。"""
        res = await client.post(
            "/api/chat/approvals",
            headers=staff_auth,
            json={"approvalId": str(uuid.uuid4()), "action": "human_finish", "isFinish": True},
        )
        assert res.status_code != 400 or "未知审批动作" not in res.json().get("detail", "")


class TestStaffReviewGate:
    async def test_staff_reject_escalation_200(self, client, staff_auth, esc_thread):
        res = await client.post(
            "/api/chat/approvals",
            headers={**staff_auth, "x-tenant-id": "aurora"},
            json={"approvalId": esc_thread["approvalId"], "action": "reject", "rejectionReason": "证据不足,驳回转人工"},
        )
        assert res.status_code == 200, res.text

    async def test_staff_approve_gate_403_without_perm(self, client, esc_thread):
        """无 live_desk:approve 的在职员工代行批驳 → 403(资金语义闸)。"""
        from engine_py.analytics import rbac
        from engine_py.db import StaffMember, get_session

        from gateway_py.routers.auth import issue_token

        await rbac.ensure_menu_seed("aurora")
        email = f"wh-p4-{_TS}@aurora.test"
        async with get_session() as session:
            session.add(StaffMember(
                id=f"staff_wh_p4_{_TS}", business_id="aurora", email=email,
                display_name="P4仓储员工", role="warehouse_operator", status="enabled", password_hash=None,
            ))
            await session.commit()
        headers = {"Authorization": f"Bearer {issue_token(f'staff_wh_p4_{_TS}', email)}", "x-tenant-id": "aurora"}
        aid = str(uuid.uuid4())
        await _insert_escalation_ticket(aid, _ESC_THREAD)
        res = await client.post(
            "/api/chat/approvals",
            headers=headers,
            json={"approvalId": aid, "action": "approve"},
        )
        assert res.status_code == 403, res.text
        assert "live_desk:approve" in res.json()["detail"]

    async def test_customer_approve_unaffected_by_gate(self, client, esc_thread):
        """顾客通道(userId 归属绑定)不受员工批驳闸影响 —— 回归锚。"""
        aid = str(uuid.uuid4())
        await _insert_escalation_ticket(aid, _ESC_THREAD)
        res = await client.post(
            "/api/approvals",
            headers={"x-user-id": _P4_USER},
            json={"approvalId": aid, "action": "reject", "rejectionReason": "顾客自己撤销"},
        )
        assert res.status_code == 200, res.text


class TestRejectDoesNotRelease:
    async def test_escalation_reject_keeps_takeover(self, client, staff_auth, esc_thread):
        """批驳 ≠ 结束人工服务:rejected 终局,不发结束文案、不清坐席、不回 active。"""
        res = await client.post(
            "/api/chat/approvals",
            headers={**staff_auth, "x-tenant-id": "aurora"},
            json={"approvalId": esc_thread["approvalId"], "action": "reject", "rejectionReason": "驳回转人工"},
        )
        assert res.status_code == 200, res.text

        assert await _approval_status(esc_thread["approvalId"]) == "rejected"
        row = await _thread_row(_ESC_THREAD)
        assert row["status"] == "human_takeover"
        assert row["op"] == "op_p4_duty"
        assert await _message_count(_ESC_THREAD, "人工客服服务已结束") == 0
        assert await _message_count(_ESC_THREAD, "[人工客服]") == 0


class TestClientMsgIdIdempotency:
    async def test_replay_same_id_one_row_and_ack(self, live_server):
        """同 clientMsgId 重放:两次 ack 同 messageId、仅一行消息、unread 只 +1。"""
        import socketio as socketio_lib
        from engine_py.db import get_session

        tid = f"p4_idem_{_TS}"
        await create_thread(tid, _P4_USER, "nike")
        msg_id = f"p4msg-{uuid.uuid4()}"
        ns = "/ws/chat"
        user = socketio_lib.AsyncClient(reconnection=False)
        received: list[dict] = []
        user.on("new_message", lambda p=None: received.append(p), namespace=ns)
        await user.connect(
            live_server,
            transports=["websocket"],
            namespaces=[ns],
            auth={"tenantId": "nike", "userId": _P4_USER, "role": "user"},
        )
        try:
            await user.call(
                "join_thread", {"threadId": tid, "tenantId": "nike", "role": "user"}, namespace=ns, timeout=5
            )
            payload = {"threadId": tid, "tenantId": "nike", "role": "user", "content": "幂等重放消息", "clientMsgId": msg_id}
            ack1 = await user.call("send_message", payload, namespace=ns, timeout=5)
            ack2 = await user.call("send_message", payload, namespace=ns, timeout=5)
            assert ack1["success"] is True and ack2["success"] is True
            assert ack1["messageId"] == msg_id
            assert ack2["messageId"] == msg_id  # 重放 ack 回既有 id
            import asyncio as _aio

            for _ in range(20):
                if len(received) >= 2:
                    break
                await _aio.sleep(0.1)
            assert len(received) == 2, received  # 重放照样广播,前端按 id 去重
            assert all(m.get("id") == msg_id for m in received), received

            async with get_session() as session:
                row = (
                    await session.execute(
                        text(
                            'SELECT (SELECT COUNT(*) FROM messages WHERE id = :mid) AS rows, '
                            'COALESCE((SELECT unread_count FROM threads WHERE id = :tid), 0) AS unread'
                        ).bindparams(mid=msg_id, tid=tid)
                    )
                ).mappings().one()
            assert row["rows"] == 1  # ON CONFLICT 静默,时间线不双行
            assert row["unread"] == 1  # 重放不重复计数
        finally:
            await user.disconnect()

    async def test_invalid_client_msg_id_falls_back_to_uuid(self, live_server):
        import re as _re

        import socketio as socketio_lib

        tid = f"p4_idem_bad_{_TS}"
        ns = "/ws/chat"
        user = socketio_lib.AsyncClient(reconnection=False)
        await user.connect(
            live_server,
            transports=["websocket"],
            namespaces=[ns],
            auth={"tenantId": "nike", "userId": _P4_USER, "role": "user"},
        )
        try:
            ack = await user.call(
                "send_message",
                {"threadId": tid, "tenantId": "nike", "role": "user", "content": "坏 id 回落", "clientMsgId": "x"},
                namespace=ns,
                timeout=5,
            )
            assert ack["success"] is True
            assert _re.match(r"^[0-9a-f-]{36}$", ack["messageId"])  # 服务端 uuid4,坏值不透传
        finally:
            await user.disconnect()
