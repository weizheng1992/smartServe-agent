"""商户管理面统一身份闸契约(2026-09-26 夜审 A4 收口)。

`/api/admin/*`(merchant.py 会话/订单/审批族)此前匿名可读写 —— 会话明文、
发货、审批裁决全是裸奔面。收口后语义:

- 无/坏 Bearer JWT → 401(身份闸,先于一切业务逻辑);
- JWT 有效但邮箱非在职员工(查无 staff 行 / status != enabled)→ 403;
- 租户参数与员工真租户不一致(含 "all" 聚合)→ 403(不变量 #1);
- 审批裁决对象级校验:工单归属他租 → 403(不依赖 gatekeeper 内部)。
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded", "staff_auth")


class TestIdentityGate:
    async def test_orders_list_without_token_is_401(self, client):
        res = await client.get("/api/admin/orders")
        assert res.status_code == 401

    async def test_orders_list_with_garbage_token_is_401(self, client):
        res = await client.get("/api/admin/orders", headers={"Authorization": "Bearer not-a-jwt"})
        assert res.status_code == 401

    async def test_valid_jwt_without_staff_row_is_403(self, client):
        from gateway_py.routers.auth import issue_token

        res = await client.get(
            "/api/admin/orders",
            headers={"Authorization": f"Bearer {issue_token('u_ghost', f'ghost-{_TS}@nowhere.test')}"},
        )
        assert res.status_code == 403

    async def test_disabled_staff_is_403(self, client):
        from engine_py.db import StaffMember, get_session

        from gateway_py.routers.auth import issue_token

        email = f"disabled-{_TS}@aurora.test"
        async with get_session() as session:
            session.add(
                StaffMember(
                    id=f"staff_disabled_{_TS}",
                    business_id="aurora",
                    email=email,
                    display_name="离职员工",
                    role="admin",
                    status="disabled",
                    password_hash="x",
                )
            )
            await session.commit()

        res = await client.get(
            "/api/admin/orders", headers={"Authorization": f"Bearer {issue_token('u_disabled', email)}"}
        )
        assert res.status_code == 403

    async def test_orders_list_with_enabled_staff_is_200(self, client, staff_auth):
        res = await client.get("/api/admin/orders", headers=staff_auth)
        assert res.status_code == 200
        assert res.json()["success"] is True


class TestObjectLevelTenantGate:
    async def test_approve_cross_tenant_ticket_is_403(self, client, staff_auth):
        """aurora 员工裁决 nike 工单:对象级 403,工单状态不得翻转。"""
        from engine_py.db import get_session

        aid = str(uuid.uuid4())
        tid = f"gate_cross_tenant_{_TS}"
        await create_thread(tid, "u_gate_cross", "nike")
        async with get_session() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                    "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, 'nike', 'waiting', 'processRefund', "
                    "'跨租户闸门工单', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') ON CONFLICT (id) DO NOTHING"
                ).bindparams(id=aid, tid=tid)
            )
            await session.commit()

        res = await client.post(
            "/api/admin/approvals",
            json={"approvalId": aid, "action": "approve", "actor": "merchant_operator"},
            headers=staff_auth,
        )
        assert res.status_code == 403
        assert res.json()["success"] is False

        async with get_session() as session:
            row = (
                await session.execute(
                    sa.text("SELECT status FROM pending_approvals WHERE id = CAST(:aid AS uuid)").bindparams(aid=aid)
                )
            ).first()
        assert row is not None and row[0] == "waiting", "被拒裁决不得翻转工单状态"

    async def test_approve_own_tenant_ticket_is_200(self, client, staff_auth):
        """正控:同租户工单照常裁决(闸门不得误伤合法操作)。"""
        from engine_py.db import get_session

        aid = str(uuid.uuid4())
        tid = f"gate_own_tenant_{_TS}"
        await create_thread(tid, "u_gate_own", "aurora")
        async with get_session() as session:
            await session.execute(
                sa.text(
                    "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                    "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, 'aurora', 'waiting', 'processRefund', "
                    "'同租户闸门正控', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') ON CONFLICT (id) DO NOTHING"
                ).bindparams(id=aid, tid=tid)
            )
            await session.commit()

        res = await client.post(
            "/api/admin/approvals",
            json={"approvalId": aid, "action": "approve", "actor": "merchant_operator"},
            headers=staff_auth,
        )
        assert res.status_code == 200, res.text
        assert res.json()["success"] is True
