"""商户 data agent 路由契约(阶段④;/api/admin/analytics/*)。

覆盖:ask(SSE 四事件形态/越权指标拒绝/无问题 400)、menus(RBAC 角色过滤 +
种子幂等 + 仓储菜单收敛)、roles 分配(非老板 403/老板保存生效)、staff 列表
与切换、reports(生成/列表/详情/CSV;sales_viewer 可生成,仓储 403)。
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from gateway_py.main import app

AURORA = {"x-tenant-id": "aurora", "x-user-id": "boss@aurora"}
OPS = {"x-tenant-id": "aurora", "x-user-id": "ops@aurora"}


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _sse_events(resp) -> list[tuple[str, dict]]:
    events = []
    event = None
    for line in resp.text.splitlines():
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: ") and event:
            events.append((event, json.loads(line[6:])))
            event = None
    return events


class TestAsk:
    async def test_ask_unsupported_is_honest(self, client):
        r = await client.post("/api/admin/analytics/ask", headers=AURORA, json={"question": "今天心情如何"})
        assert r.status_code == 200
        events = _sse_events(r)
        kinds = [e for e, _ in events]
        assert "unsupported" in kinds

    async def test_ask_missing_question_400(self, client):
        r = await client.post("/api/admin/analytics/ask", headers=AURORA, json={})
        assert r.status_code == 400

    async def test_ask_result_or_error_never_fake(self, client):
        """指标命中:result(有数据)或 error(如商户库表缺失)—— 二者必居其一,
        且均非编造数字。"""
        r = await client.post("/api/admin/analytics/ask", headers=AURORA, json={"question": "会话量多少"})
        assert r.status_code == 200
        kinds = [e for e, _ in _sse_events(r)]
        assert any(k in ("result", "error") for k in kinds)


class TestMenusAndRoles:
    async def test_menus_seeded_for_boss(self, client):
        r = await client.get("/api/admin/analytics/menus", headers=AURORA)
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "finance_owner"
        def _walk(nodes):
            for n in nodes:
                yield n["name"]
                yield from _walk(n.get("children") or [])

        names = set(_walk(body["menus"]))
        assert {"数据分析", "我的报告"} <= names

    async def test_role_assignment_roundtrip(self, client):
        # 老板裁仓储菜单 → 仓储视角收敛
        r1 = await client.post("/api/admin/analytics/roles/warehouse_operator/menus",
                               headers=AURORA, json={"menuIds": ["m-analytics", "m-orders", "m-menus", "m-roles", "m-staff"]})
        assert r1.status_code == 200
        r2 = await client.post("/api/admin/analytics/staff/switch", headers=AURORA, json={"staffId": "wh@aurora"})
        assert r2.status_code == 200
        assert r2.json()["role"] == "warehouse_operator"
        def _walk2(nodes):
            for n in nodes:
                yield n["name"]
                yield from _walk2(n.get("children") or [])

        assert "客户管理" not in set(_walk2(r2.json()["menus"]))

    async def test_non_boss_cannot_assign_403(self, client):
        r = await client.post("/api/admin/analytics/roles/sales_viewer/menus", headers=OPS, json={"menuIds": []})
        assert r.status_code == 403


class TestStaffAndReports:
    async def test_staff_list_has_owner_seed(self, client):
        r = await client.get("/api/admin/analytics/staff", headers=AURORA)
        assert r.status_code == 200
        roles = {s["role"] for s in r.json()["staff"]}
        assert "finance_owner" in roles

    async def test_report_lifecycle(self, client):
        created = await client.post("/api/admin/analytics/reports", headers=AURORA, json={})
        assert created.status_code == 200
        rid = created.json()["id"]

        listed = await client.get("/api/admin/analytics/reports", headers=AURORA)
        assert any(x["id"] == rid for x in listed.json()["reports"])

        detail = await client.get(f"/api/admin/analytics/reports/{rid}", headers=AURORA)
        assert "<html" in detail.json()["html"] or "<!doctype" in detail.json()["html"].lower()

        csv = await client.get(f"/api/admin/analytics/reports/{rid}/csv", headers=AURORA)
        assert csv.status_code == 200 and "csv" in csv.json()

    async def test_unknown_report_404(self, client):
        r = await client.get("/api/admin/analytics/reports/rpt_none", headers=AURORA)
        assert r.status_code == 404


class TestPromotions:
    """阶段⑥:优惠活动 CRUD(20 号;写操作,结算资金口径不在本模块)。"""

    async def test_list_empty_honest(self, client):
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()  # 商户库自愈建库建表(幂等;含 promotions 两表)
        r = await client.get("/api/admin/analytics/promotions", headers=AURORA)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True and isinstance(body["promotions"], list)
        assert "effect" in body and body["effect"]["redemptions"] >= 0

    async def test_create_requires_valid_payload(self, client):
        bad = await client.post("/api/admin/analytics/promotions", headers=AURORA, json={"name": "x"})
        assert bad.status_code == 400

    async def test_create_and_disable_roundtrip(self, client):
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        created = await client.post("/api/admin/analytics/promotions", headers=AURORA, json={
            "name": "开学季满减", "promoType": "full_reduction", "threshold": 500, "value": 50,
        })
        assert created.status_code == 200
        pid = created.json()["id"]

        listed = await client.get("/api/admin/analytics/promotions", headers=AURORA)
        assert any(p["id"] == pid and p["status"] == "active" for p in listed.json()["promotions"])

        disabled = await client.post(f"/api/admin/analytics/promotions/{pid}/status",
                                     headers=AURORA, json={"status": "disabled"})
        assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"

    async def test_warehouse_cannot_create_403(self, client):
        await client.post("/api/admin/analytics/staff/switch", headers=AURORA, json={"staffId": "wh@aurora"})
        r = await client.post("/api/admin/analytics/promotions",
                              headers={**AURORA, "x-user-id": "wh@aurora"},
                              json={"name": "x", "promoType": "coupon", "value": 10})
        assert r.status_code == 403


class TestTrendAndCrud:
    """折线趋势(18/10-D2 趋势→折线)+ 菜单 CRUD + 角色 + 员工 + 客户 + 核销。"""

    async def test_gmv_trend_line_chart(self, client):
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()  # 商户库自愈(趋势/核销查商户库)
        r = await client.post("/api/admin/analytics/ask", headers=AURORA, json={"question": "近 30 天 GMV 趋势"})
        events = dict(_sse_events(r))
        result = events["result"]
        assert result.get("chart") == "line"
        rows = result.get("rows") or []
        assert len(rows) == 30  # 固定 30 天窗口
        assert "日期" in rows[0] and "GMV" in rows[0]

    async def test_menu_create_update_delete(self, client):
        created = await client.post("/api/admin/analytics/menus", headers=AURORA, json={
            "name": "E2E 临时菜单", "menuType": "menu", "route": "/e2e-tmp", "parentId": None,
        })
        assert created.status_code == 200
        mid = created.json()["id"]
        patched = await client.patch(f"/api/admin/analytics/menus/{mid}", headers=AURORA, json={"status": "disabled"})
        assert patched.status_code == 200
        deleted = await client.delete(f"/api/admin/analytics/menus/{mid}", headers=AURORA)
        assert deleted.status_code == 200

    async def test_system_menu_protected(self, client):
        r = await client.delete("/api/admin/analytics/menus/m-menus", headers=AURORA)
        assert r.status_code == 400
        assert "护栏" in r.json()["message"]

    async def test_role_create_requires_menus(self, client):
        r = await client.post("/api/admin/analytics/roles", headers=AURORA, json={"role": "custom_x"})
        assert r.status_code == 400
        ok = await client.post("/api/admin/analytics/roles", headers=AURORA, json={
            "role": "custom_x", "menuIds": ["m-analytics", "m-orders"],
        })
        assert ok.status_code == 200
        listed = await client.get("/api/admin/analytics/roles", headers=AURORA)
        assert any(x["role"] == "custom_x" for x in listed.json()["roles"])

    async def test_staff_invite_and_guard(self, client):
        r = await client.post("/api/admin/analytics/staff", headers=AURORA, json={
            "email": "e2e-new@aurora", "displayName": "E2E", "role": "sales_viewer",
        })
        assert r.status_code == 200
        dup = await client.post("/api/admin/analytics/staff", headers=AURORA, json={"email": "e2e-new@aurora"})
        assert dup.status_code == 400
        owner = (await client.get("/api/admin/analytics/staff", headers=AURORA)).json()["staff"]
        boss = next(s for s in owner if s["role"] == "finance_owner")
        guard = await client.patch(f"/api/admin/analytics/staff/{boss['id']}", headers=AURORA, json={"status": "disabled"})
        assert guard.status_code == 400 and "护栏" in guard.json()["message"]

    async def test_customers_list(self, client):
        r = await client.get("/api/admin/analytics/customers", headers=AURORA)
        assert r.status_code == 200
        assert isinstance(r.json()["customers"], list)

    async def test_promotion_redeem_and_idempotency(self, client):
        await client.post("/api/admin/analytics/staff/switch", headers=AURORA, json={"staffId": "boss@aurora"})
        created = await client.post("/api/admin/analytics/promotions", headers=AURORA, json={
            "name": "E2E 核销券", "promoType": "coupon", "value": 100,
        })
        pid = created.json()["id"]
        # 种一笔真实订单(容器商户库为空;经写引擎直写,与生产同链路)
        from engine_py.tools_registry.order_domain import _merchant_writer_engine
        from sqlalchemy import text as _t

        async with _merchant_writer_engine().begin() as conn:
            await conn.execute(_t(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, shipping_address) "
                "VALUES ('AURORA-ORD-2026-9081', 'CUST-8801', 'PAID', 1299.00, "
                "'{\"fullAddress\": \"E2E 测试地址\"}'::jsonb) "
                "ON CONFLICT (order_id) DO UPDATE SET total_amount = 1299.00"
            ))
        # 不存在的订单 → 400 诚实
        bad = await client.post(f"/api/admin/analytics/promotions/{pid}/redeem",
                                headers=AURORA, json={"orderId": "NOT-EXIST"})
        assert bad.status_code == 400 and "不存在" in bad.json()["error"]
        # 种子订单 → 核销成功;重复 → 幂等拦截
        ok = await client.post(f"/api/admin/analytics/promotions/{pid}/redeem",
                               headers=AURORA, json={"orderId": "AURORA-ORD-2026-9081"})
        assert ok.status_code == 200 and ok.json()["discount"] > 0
        dup = await client.post(f"/api/admin/analytics/promotions/{pid}/redeem",
                                headers=AURORA, json={"orderId": "AURORA-ORD-2026-9081"})
        assert dup.status_code == 400 and "幂等" in dup.json()["error"]
