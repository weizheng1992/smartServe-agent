"""credits 积分池路由契约(2026-10-21 用量配额闸,票 05)。

平台面:POST /api/billing/credits/adjust(手动充值/核减,台账留审计)+
GET /api/billing/credits/{businessId}(余额+流水)—— require_platform_admin,
匿名 401 / 普通员工 403;商户面:GET /api/admin/credits(本租户只读,
staff_context 闸,无跨租户查询参数)。
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture()
async def platform(client):
    """平台运营者 JWT(与 test_http_routes_contract 同纪律:ASGITransport 不触发
    lifespan,显式种子后走真登录)。"""
    from engine_py.analytics import rbac

    await rbac.ensure_platform_admin()
    password = os.environ.get("E2E_ACCOUNT_PASSWORD", "agent-all-dev")
    r = await client.post("/api/auth/login", json={"email": "platform@aurora", "password": password})
    assert r.status_code == 200, f"平台登录失败: {r.text}"
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}


def _initial() -> int:
    return int(os.environ.get("AI_MERCHANT_INITIAL_CREDITS", "1000"))


class TestBillingCreditsPlatform:
    async def test_anonymous_401(self, client):
        res = await client.post(
            "/api/billing/credits/adjust", json={"businessId": "nike", "delta": 100, "reason": "x"}
        )
        assert res.status_code == 401
        res = await client.get("/api/billing/credits/nike")
        assert res.status_code == 401

    async def test_adjust_and_detail_roundtrip(self, client, platform):
        biz = f"cred_{uuid.uuid4().hex[:10]}"
        res = await client.post(
            "/api/billing/credits/adjust",
            headers=platform,
            json={"businessId": biz, "delta": 500, "reason": "测试充值"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["data"]["balance"] == _initial() + 500

        res = await client.get(f"/api/billing/credits/{biz}", headers=platform)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["balance"] == _initial() + 500
        # 懒初始化与首笔 adjust 同事务,created_at 同为事务时间戳,新→旧排序在
        # 二者间不稳定 —— 断言成员与审计字段,不钉同事务行间序
        reasons = [t["reason"] for t in data["transactions"]]
        assert any(r.startswith("admin_adjust") for r in reasons)
        assert "initial_grant" in reasons
        adjust_row = next(t for t in data["transactions"] if t["reason"].startswith("admin_adjust"))
        assert adjust_row["operator"]

    async def test_over_draft_rejected_400(self, client, platform):
        biz = f"cred_{uuid.uuid4().hex[:10]}"
        # 懒初始化即有赠额,核减须超过赠额才触守卫(余额不可穿零)
        res = await client.post(
            "/api/billing/credits/adjust",
            headers=platform,
            json={"businessId": biz, "delta": -10_000_000, "reason": "超额核减"},
        )
        assert res.status_code == 400
        assert res.json()["success"] is False

    async def test_zero_delta_and_empty_reason_400(self, client, platform):
        res = await client.post(
            "/api/billing/credits/adjust",
            headers=platform,
            json={"businessId": "nike", "delta": 0, "reason": "x"},
        )
        assert res.status_code == 400
        res = await client.post(
            "/api/billing/credits/adjust",
            headers=platform,
            json={"businessId": "nike", "delta": 1, "reason": "  "},
        )
        assert res.status_code == 400


class TestMerchantPortalCredits:
    async def test_staff_reads_own_tenant(self, client, staff_auth):
        res = await client.get("/api/admin/credits", headers={**staff_auth, "x-tenant-id": "aurora"})
        assert res.status_code == 200, res.text
        data = res.json()["data"]
        assert data["businessId"] == "aurora"
        assert isinstance(data["transactions"], list)

    async def test_anonymous_401(self, client):
        res = await client.get("/api/admin/credits", headers={"x-tenant-id": "aurora"})
        assert res.status_code == 401
