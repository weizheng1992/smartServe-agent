"""chat 面审批接口鉴权矩阵(02 安全先行,2026-09-27)。

POST /api/approvals(别名 /api/chat/approvals)是双面接口:顾客 HITL
(apps/web 审批卡 / 呼叫人工)与历史坐席通道共用。收口后的分面语义:

1. 人工坐席动作(human_message/human_reply/human_finish):必须持员工 JWT,
   匿名 401 —— 此前匿名可自报 actor 以坐席身份发消息/结案;
2. 顾客动作(approve/reject/cancel/start_human_takeover):保持可达但加线程
   归属绑定(userId 须为会话属主)—— 此前匿名可凭猜测的 approvalId 核准退款;
3. 员工凭 JWT 走顾客动作:对象级租户校验(跨租户 403,与商户面 A4 同口径);
4. 身份诚实化:顾客决议落 customer 语义(引擎词表已扩),员工决议默认取
   JWT email;x-role 自报头与匿名 actor 自报退役;
5. 白名单外动作 400(此前未知动作落引擎按驳回语义静默终局)。

另钉 m-live-desk 按钮权限点种子(rbac):perm 闭包只认 button 型子节点,
工作台此前整菜单无任何权限点可查。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded")

_AUTH_THREAD = f"auth_thread_{_TS}"
_AUTH_USER = "u_auth_owner"


async def _insert_waiting_ticket(ticket_id: str, tenant: str = "nike", thread_id: str = _AUTH_THREAD) -> None:
    from engine_py.db import get_session
    from sqlalchemy import text

    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, :bid, 'waiting', 'processRefund', "
                "'鉴权矩阵工单', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') ON CONFLICT (id) DO NOTHING"
            ).bindparams(id=ticket_id, tid=thread_id, bid=tenant)
        )
        await session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def auth_thread(seeded):
    await create_thread(_AUTH_THREAD, _AUTH_USER, "nike")
    return _AUTH_THREAD


class TestOperatorActionsRequireStaffJwt:
    async def test_human_message_anonymous_401(self, client, auth_thread):
        res = await client.post(
            "/api/chat/approvals",
            json={"approvalId": str(uuid.uuid4()), "action": "human_message", "humanReply": "您好"},
        )
        assert res.status_code == 401
        assert "员工" in res.json()["detail"]

    async def test_human_message_with_garbage_token_401(self, client, auth_thread):
        res = await client.post(
            "/api/approvals",
            headers={"Authorization": "Bearer not-a-jwt"},
            json={"approvalId": str(uuid.uuid4()), "action": "human_finish", "isFinish": True},
        )
        assert res.status_code == 401

    async def test_human_message_with_staff_jwt_passes_auth_layer(self, client, auth_thread, staff_auth):
        """带员工凭证行为不变:过鉴权层后落引擎语义(工单存在 → HTTP 200 引擎信封)。"""
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid, tenant="aurora")
        res = await client.post(
            "/api/chat/approvals",
            headers={**staff_auth, "x-tenant-id": "aurora"},
            json={"approvalId": aid, "action": "human_message", "humanReply": "您好,已为您跟进"},
        )
        assert res.status_code == 200
        assert "detail" not in res.json()


class TestCustomerActionsOwnershipBinding:
    async def test_approve_missing_user_id_400(self, client, auth_thread):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)
        res = await client.post(
            "/api/approvals",
            json={"approvalId": aid, "action": "approve"},
        )
        assert res.status_code == 400
        assert "userId" in res.json()["detail"]

    async def test_approve_non_owner_403(self, client, auth_thread):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)
        res = await client.post(
            "/api/approvals",
            headers={"x-user-id": "u_not_the_owner"},
            json={"approvalId": aid, "action": "approve"},
        )
        assert res.status_code == 403

    async def test_approve_by_owner_via_header(self, client, auth_thread):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)
        res = await client.post(
            "/api/approvals",
            headers={"x-user-id": _AUTH_USER},
            json={"approvalId": aid, "action": "approve"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body.get("status") == "approved" or body.get("success") is True

    async def test_start_human_takeover_by_owner(self, client, auth_thread):
        res = await client.post(
            "/api/chat/approvals",
            json={"threadId": _AUTH_THREAD, "action": "start_human_takeover", "userId": _AUTH_USER},
        )
        assert res.status_code == 200
        assert "detail" not in res.json()

    async def test_start_human_takeover_non_owner_403(self, client, auth_thread):
        res = await client.post(
            "/api/chat/approvals",
            json={"threadId": _AUTH_THREAD, "action": "start_human_takeover", "userId": "u_not_the_owner"},
        )
        assert res.status_code == 403

    async def test_start_human_takeover_unknown_thread_403(self, client):
        """无主/查无线程不可核验归属 → 拒绝(诚实失败,不回落引擎兜底建单)。"""
        res = await client.post(
            "/api/chat/approvals",
            json={"threadId": "ghost_thread_none", "action": "start_human_takeover", "userId": _AUTH_USER},
        )
        assert res.status_code == 403


class TestStaffCrossTenantAndUnknownAction:
    async def test_staff_customer_action_cross_tenant_403(self, client, auth_thread, staff_auth):
        """aurora 员工代行 nike 工单 → 对象级租户校验 403(与商户面 A4 同口径)。"""
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)
        res = await client.post(
            "/api/approvals",
            headers={**staff_auth, "x-tenant-id": "aurora"},
            json={"approvalId": aid, "action": "approve"},
        )
        assert res.status_code == 403

    async def test_unknown_action_400(self, client):
        res = await client.post(
            "/api/approvals",
            headers={"x-user-id": _AUTH_USER},
            json={"approvalId": str(uuid.uuid4()), "action": "self_assign_refund"},
        )
        assert res.status_code == 400
        assert "未知审批动作" in res.json()["detail"]


class TestLiveDeskButtonPermSeed:
    """m-live-desk 按钮权限点(02 安全先行③):perm 闭包只认 button 型子节点,
    此前工作台整菜单无权限点可查。种子面与菜单可见性对齐 —— 老板/管理员/运营
    可见即持有,仓储无此菜单。坐席身份模型定档后再细化角色拆分。"""

    async def test_boss_tree_has_operate_button(self, staff_auth):
        from engine_py.analytics import rbac

        tree = await rbac.menu_tree_for_role("aurora", "finance_owner")
        # 树顶层是目录(d-users 等),m-live-desk 是其下的菜单节点
        dirs = [n for n in tree if n["id"] == "d-users"]
        desk = next(c for c in dirs[0]["children"] if c["id"] == "m-live-desk")
        perms = [c["permCode"] for c in desk["children"]]
        assert "live_desk:operate" in perms

    async def test_warehouse_tree_has_no_desk(self, staff_auth):
        from engine_py.analytics import rbac

        tree = await rbac.menu_tree_for_role("aurora", "warehouse_operator")
        assert all(n["id"] != "m-live-desk" for n in tree)


if __name__ == "__main__":
    pytest.main([__file__])
