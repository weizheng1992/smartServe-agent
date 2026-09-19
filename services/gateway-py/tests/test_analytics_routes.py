"""商户 data agent 路由契约(阶段④;/api/admin/analytics/*;0013 JWT 收口)。

覆盖:JWT 身份(无 token 401/未知员工 403)、ask(SSE 四事件形态/越权指标拒绝/
无问题 400)、menus(RBAC 角色过滤 + 种子幂等 + 仓储菜单收敛)、roles 分配(非老板
403/老板保存生效/勾选即生效的按钮权限授予与回收)、staff 列表与老板签发切换、
reports(生成/列表/详情/CSV;report:gen 权限点驱动)、促销(perm 驱动)。
"""

from __future__ import annotations

import json
import os

import pytest
from httpx import ASGITransport, AsyncClient

from gateway_py.main import app

TENANT = {"x-tenant-id": "aurora"}
DEV_PASSWORD = os.environ.get("E2E_ACCOUNT_PASSWORD", "agent-all-dev")


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture()
async def auth(client):
    """真实登录换 Bearer token(email → staff_members 角色;0013 身份链路)。"""
    from engine_py.analytics import rbac

    await rbac.ensure_defaults("aurora")

    async def _login(email: str = "test@example.com", password: str = DEV_PASSWORD) -> dict[str, str]:
        r = await client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, f"登录失败 {email}: {r.text}"
        return {**TENANT, "Authorization": f"Bearer {r.json()['data']['token']}"}

    return _login


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


class TestJwtIdentity:
    """0013 收口:x-user-id 头不再被信任,身份唯一来源是 Bearer JWT。"""

    async def test_menus_without_token_401(self, client):
        r = await client.get("/api/admin/analytics/menus", headers={**TENANT, "x-user-id": "test@example.com"})
        assert r.status_code == 401

    async def test_menus_with_bad_token_401(self, client, auth):
        r = await client.get("/api/admin/analytics/menus", headers={**TENANT, "Authorization": "Bearer not-a-jwt"})
        assert r.status_code == 401

    async def test_switch_requires_boss_403(self, client, auth):
        ops = await auth("ops@aurora")
        r = await client.post("/api/admin/analytics/staff/switch", headers=ops, json={"staffId": "wh@aurora"})
        assert r.status_code == 403

    async def test_switch_mints_target_token(self, client, auth):
        boss = await auth()
        sw = await client.post("/api/admin/analytics/staff/switch", headers=boss, json={"staffId": "wh@aurora"})
        assert sw.status_code == 200
        body = sw.json()
        assert body["role"] == "warehouse_operator" and body["token"]
        menus = await client.get("/api/admin/analytics/menus",
                                 headers={**TENANT, "Authorization": f"Bearer {body['token']}"})
        assert menus.json()["role"] == "warehouse_operator"


class TestAsk:
    async def test_ask_unsupported_is_honest(self, client, auth):
        boss = await auth()
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": "今天心情如何"})
        assert r.status_code == 200
        events = _sse_events(r)
        kinds = [e for e, _ in events]
        assert "unsupported" in kinds

    async def test_ask_missing_question_400(self, client, auth):
        boss = await auth()
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={})
        assert r.status_code == 400

    async def test_ask_result_or_error_never_fake(self, client, auth):
        """指标命中:result(有数据)或 error(如商户库表缺失)—— 二者必居其一,
        且均非编造数字。"""
        boss = await auth()
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": "会话量多少"})
        assert r.status_code == 200
        kinds = [e for e, _ in _sse_events(r)]
        assert any(k in ("result", "error") for k in kinds)


class TestMenusAndRoles:
    async def test_menus_seeded_for_boss(self, client, auth):
        boss = await auth()
        r = await client.get("/api/admin/analytics/menus", headers=boss)
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "finance_owner"
        assert "prod:edit" in body["perms"]  # 0013:老板权限点 = 全量已登记按钮

        def _walk(nodes):
            for n in nodes:
                yield n["name"]
                yield from _walk(n.get("children") or [])

        names = set(_walk(body["menus"]))
        assert {"数据分析", "我的报告"} <= names

    async def test_role_assignment_roundtrip(self, client, auth):
        # 老板裁仓储菜单 → 经老板签发的仓储 token 视角收敛
        boss = await auth()
        r1 = await client.post("/api/admin/analytics/roles/warehouse_operator/menus",
                               headers=boss, json={"menuIds": ["m-analytics", "m-orders", "m-menus", "m-roles", "m-staff"]})
        assert r1.status_code == 200
        sw = await client.post("/api/admin/analytics/staff/switch", headers=boss, json={"staffId": "wh@aurora"})
        wh_headers = {**TENANT, "Authorization": f"Bearer {sw.json()['token']}"}
        r2 = await client.get("/api/admin/analytics/menus", headers=wh_headers)
        assert r2.status_code == 200
        assert r2.json()["role"] == "warehouse_operator"
        def _walk2(nodes):
            for n in nodes:
                yield n["name"]
                yield from _walk2(n.get("children") or [])

        assert "客户管理" not in set(_walk2(r2.json()["menus"]))

    async def test_role_menus_readback(self, client, auth):
        """角色权限分配明细回读(角色管理页勾选树回填)。"""
        boss = await auth()
        ids = ["m-analytics", "btn-report-gen"]
        await client.post("/api/admin/analytics/roles/custom_readback/menus", headers=boss, json={"menuIds": ids})
        r = await client.get("/api/admin/analytics/roles/custom_readback/menus", headers=boss)
        assert r.status_code == 200
        assert set(ids) <= set(r.json()["menuIds"])

    async def test_non_boss_cannot_assign_403(self, client, auth):
        ops = await auth("ops@aurora")
        r = await client.post("/api/admin/analytics/roles/sales_viewer/menus", headers=ops, json={"menuIds": []})
        assert r.status_code == 403

    async def test_button_perm_grant_and_revoke(self, client, auth):
        """0013 核心:按钮权限点由 role_menus 动态派生 —— 勾选即生效,取消即回收。"""
        from engine_py.analytics.rbac import DEFAULT_ROLE_MENUS

        boss = await auth()
        sw = await client.post("/api/admin/analytics/staff/switch", headers=boss, json={"staffId": "wh@aurora"})
        wh = {**TENANT, "Authorization": f"Bearer {sw.json()['token']}"}

        # 默认仓储无 report:gen → 生成报告 403
        denied = await client.post("/api/admin/analytics/reports", headers=wh, json={})
        assert denied.status_code == 403

        # 勾上「生成报告」按钮 → 立即可用
        granted_ids = [*DEFAULT_ROLE_MENUS["warehouse_operator"], "btn-report-gen"]
        ok = await client.post("/api/admin/analytics/roles/warehouse_operator/menus",
                               headers=boss, json={"menuIds": granted_ids})
        assert ok.status_code == 200
        allowed = await client.post("/api/admin/analytics/reports", headers=wh, json={})
        assert allowed.status_code == 200

        # 取消勾选 → 立即回收
        await client.post("/api/admin/analytics/roles/warehouse_operator/menus",
                          headers=boss, json={"menuIds": DEFAULT_ROLE_MENUS["warehouse_operator"]})
        revoked = await client.post("/api/admin/analytics/reports", headers=wh, json={})
        assert revoked.status_code == 403

    async def test_metric_perm_via_button(self, client, auth):
        """metric: 前缀权限点 → 指标闭集动态生效;无 metric: 点回落内置三档。"""
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        mids = []
        for perm in ("metric:gmv", "metric:gmv_trend"):  # 指标名 = metric_registry key
            created = await client.post("/api/admin/analytics/menus", headers=boss, json={
                "name": f"{perm} 可见", "menuType": "button", "permCode": perm, "parentId": "m-analytics",
            })
            assert created.status_code == 200
            mids.append(created.json()["id"])
        role = await client.post("/api/admin/analytics/roles", headers=boss, json={
            "role": "custom_metric_e2e", "menuIds": ["d-data", "m-analytics", *mids],
        })
        assert role.status_code == 200

        invite = await client.post("/api/admin/analytics/staff", headers=boss, json={
            "email": "metric-e2e@aurora", "displayName": "指标E2E", "role": "custom_metric_e2e",
        })
        assert invite.status_code in (200, 400)  # 400 = 上一轮已存在,复用即可
        staff_hdrs = await auth("metric-e2e@aurora")

        # 自定义角色持 metric:gmv_trend → GMV 趋势真实出折线(权限放行到执行层)
        r = await client.post("/api/admin/analytics/ask", headers=staff_hdrs, json={"question": "近 30 天 GMV 趋势"})
        events = dict(_sse_events(r))
        assert events.get("result", {}).get("chart") == "line"

        # 仓储无 metric: 点,回落内置闭集(无 gmv_trend)→ 越权兜底拒绝
        sw = await client.post("/api/admin/analytics/staff/switch", headers=boss, json={"staffId": "wh@aurora"})
        wh = {**TENANT, "Authorization": f"Bearer {sw.json()['token']}"}
        denied = await client.post("/api/admin/analytics/ask", headers=wh, json={"question": "近 30 天 GMV 趋势"})
        denied_events = dict(_sse_events(denied))
        assert denied_events.get("unsupported", {}).get("message", "").startswith("当前角色无权查看该指标")


class TestStaffAndReports:
    async def test_staff_list_has_owner_seed(self, client, auth):
        boss = await auth()
        r = await client.get("/api/admin/analytics/staff", headers=boss)
        assert r.status_code == 200
        roles = {s["role"] for s in r.json()["staff"]}
        assert "finance_owner" in roles

    async def test_report_lifecycle(self, client, auth):
        boss = await auth()
        created = await client.post("/api/admin/analytics/reports", headers=boss, json={})
        assert created.status_code == 200
        rid = created.json()["id"]

        listed = await client.get("/api/admin/analytics/reports", headers=boss)
        assert any(x["id"] == rid for x in listed.json()["reports"])

        detail = await client.get(f"/api/admin/analytics/reports/{rid}", headers=boss)
        assert "<html" in detail.json()["html"] or "<!doctype" in detail.json()["html"].lower()

        csv = await client.get(f"/api/admin/analytics/reports/{rid}/csv", headers=boss)
        assert csv.status_code == 200 and "csv" in csv.json()

    async def test_report_csv_requires_perm(self, client, auth):
        """report:csv 权限点驱动导出(0013 前该端点无校验)。"""
        boss = await auth()
        rid = (await client.post("/api/admin/analytics/reports", headers=boss, json={})).json()["id"]
        sw = await client.post("/api/admin/analytics/staff/switch", headers=boss, json={"staffId": "wh@aurora"})
        wh = {**TENANT, "Authorization": f"Bearer {sw.json()['token']}"}
        r = await client.get(f"/api/admin/analytics/reports/{rid}/csv", headers=wh)
        assert r.status_code == 403

    async def test_unknown_report_404(self, client, auth):
        boss = await auth()
        r = await client.get("/api/admin/analytics/reports/rpt_none", headers=boss)
        assert r.status_code == 404


class TestPromotions:
    """阶段⑥:优惠活动 CRUD(20 号;perm 驱动,结算资金口径不在本模块)。"""

    async def test_list_empty_honest(self, client, auth):
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()  # 商户库自愈建库建表(幂等;含 promotions 两表)
        boss = await auth()
        r = await client.get("/api/admin/analytics/promotions", headers=boss)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True and isinstance(body["promotions"], list)
        assert "effect" in body and body["effect"]["redemptions"] >= 0

    async def test_create_requires_valid_payload(self, client, auth):
        boss = await auth()
        bad = await client.post("/api/admin/analytics/promotions", headers=boss, json={"name": "x"})
        assert bad.status_code == 400

    async def test_create_and_disable_roundtrip(self, client, auth):
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        created = await client.post("/api/admin/analytics/promotions", headers=boss, json={
            "name": "开学季满减", "promoType": "full_reduction", "threshold": 500, "value": 50,
        })
        assert created.status_code == 200
        pid = created.json()["id"]

        listed = await client.get("/api/admin/analytics/promotions", headers=boss)
        assert any(p["id"] == pid and p["status"] == "active" for p in listed.json()["promotions"])

        disabled = await client.post(f"/api/admin/analytics/promotions/{pid}/status",
                                     headers=boss, json={"status": "disabled"})
        assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"

    async def test_warehouse_cannot_create_403(self, client, auth):
        boss = await auth()
        sw = await client.post("/api/admin/analytics/staff/switch", headers=boss, json={"staffId": "wh@aurora"})
        wh = {**TENANT, "Authorization": f"Bearer {sw.json()['token']}"}
        r = await client.post("/api/admin/analytics/promotions",
                              headers=wh,
                              json={"name": "x", "promoType": "coupon", "value": 10})
        assert r.status_code == 403

    async def test_grant_coupon_and_customer_coupons(self, client, auth):
        """发券给客户(0014;复用领券护栏)+ 客户关联券回读。"""
        from sqlalchemy import text as _t

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        created = await client.post("/api/admin/analytics/promotions", headers=boss, json={
            "name": "E2E 定向券", "promoType": "coupon", "value": 20,
        })
        pid = created.json()["id"]

        # customerId 必传
        bad = await client.post(f"/api/admin/analytics/promotions/{pid}/grant", headers=boss, json={})
        assert bad.status_code == 400

        # 客户档案(customer_id 即商城用户 uid;user_coupons.user_id 同源)
        from engine_py.tools_registry.order_domain import _merchant_writer_engine

        async with _merchant_writer_engine().begin() as conn:
            await conn.execute(_t(
                "INSERT INTO merchant_customers (customer_id, name, phone) "
                "VALUES ('CUST-GRANT-E2E', '发券对象', '13800000000') "
                "ON CONFLICT (customer_id) DO NOTHING"
            ))

        ok = await client.post(f"/api/admin/analytics/promotions/{pid}/grant",
                               headers=boss, json={"customerId": "CUST-GRANT-E2E"})
        assert ok.status_code == 200
        # 同人同活动一次 → 护栏拦截
        dup = await client.post(f"/api/admin/analytics/promotions/{pid}/grant",
                                headers=boss, json={"customerId": "CUST-GRANT-E2E"})
        assert dup.status_code == 400

        listed = await client.get("/api/admin/analytics/customers/CUST-GRANT-E2E/coupons", headers=boss)
        assert listed.status_code == 200
        coupons = listed.json()["coupons"]
        assert any(c["name"] == "E2E 定向券" and c["status"] == "claimed" for c in coupons)

    async def test_non_boss_cannot_grant_403(self, client, auth):
        """发券走 promo:create 权限点(仓储种子未勾选 → 403)。"""
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        sw = await client.post("/api/admin/analytics/staff/switch", headers=boss, json={"staffId": "wh@aurora"})
        wh = {**TENANT, "Authorization": f"Bearer {sw.json()['token']}"}
        r = await client.post("/api/admin/analytics/promotions/00000000-0000-0000-0000-000000000000/grant",
                              headers=wh, json={"customerId": "CUST-X"})
        assert r.status_code == 403


class TestTrendAndCrud:
    """折线趋势(18/10-D2 趋势→折线)+ 菜单 CRUD + 角色 + 员工 + 客户 + 核销。"""

    async def test_gmv_trend_line_chart(self, client, auth):
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()  # 商户库自愈(趋势/核销查商户库)
        boss = await auth()
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": "近 30 天 GMV 趋势"})
        events = dict(_sse_events(r))
        result = events["result"]
        assert result.get("chart") == "line"
        rows = result.get("rows") or []
        assert len(rows) == 30  # 固定 30 天窗口
        assert "日期" in rows[0] and "GMV" in rows[0]

    async def test_menu_create_update_delete(self, client, auth):
        boss = await auth()
        created = await client.post("/api/admin/analytics/menus", headers=boss, json={
            "name": "E2E 临时菜单", "menuType": "menu", "route": "/e2e-tmp", "parentId": None,
        })
        assert created.status_code == 200
        mid = created.json()["id"]
        patched = await client.patch(f"/api/admin/analytics/menus/{mid}", headers=boss, json={"status": "disabled"})
        assert patched.status_code == 200
        deleted = await client.delete(f"/api/admin/analytics/menus/{mid}", headers=boss)
        assert deleted.status_code == 200

    async def test_system_menu_protected(self, client, auth):
        boss = await auth()
        r = await client.delete("/api/admin/analytics/menus/m-menus", headers=boss)
        assert r.status_code == 400
        assert "护栏" in r.json()["message"]

    async def test_role_create_requires_menus(self, client, auth):
        boss = await auth()
        r = await client.post("/api/admin/analytics/roles", headers=boss, json={"role": "custom_x"})
        assert r.status_code == 400
        ok = await client.post("/api/admin/analytics/roles", headers=boss, json={
            "role": "custom_x", "menuIds": ["m-analytics", "m-orders"],
        })
        assert ok.status_code == 200
        listed = await client.get("/api/admin/analytics/roles", headers=boss)
        assert any(x["role"] == "custom_x" for x in listed.json()["roles"])

    async def test_role_create_rejects_builtin(self, client, auth):
        """0013 护栏:内置角色的权限面不可被「新建同名角色」覆盖。"""
        boss = await auth()
        r = await client.post("/api/admin/analytics/roles", headers=boss, json={
            "role": "sales_viewer", "menuIds": ["m-analytics"],
        })
        assert r.status_code == 400

    async def test_staff_invite_and_guard(self, client, auth):
        boss = await auth()
        r = await client.post("/api/admin/analytics/staff", headers=boss, json={
            "email": "e2e-new@aurora", "displayName": "E2E", "role": "sales_viewer",
        })
        assert r.status_code == 200
        dup = await client.post("/api/admin/analytics/staff", headers=boss, json={"email": "e2e-new@aurora"})
        assert dup.status_code == 400
        owner = (await client.get("/api/admin/analytics/staff", headers=boss)).json()["staff"]
        boss_row = next(s for s in owner if s["role"] == "finance_owner")
        guard = await client.patch(f"/api/admin/analytics/staff/{boss_row['id']}", headers=boss, json={"status": "disabled"})
        assert guard.status_code == 400 and "护栏" in guard.json()["message"]

    async def test_invited_staff_can_login(self, client, auth):
        """0013:邀请即带种子密码,新员工可真实登录(JWT 身份链路闭环)。"""
        boss = await auth()
        await client.post("/api/admin/analytics/staff", headers=boss, json={
            "email": "login-e2e@aurora", "displayName": "登录E2E", "role": "sales_viewer",
        })
        hdrs = await auth("login-e2e@aurora")
        menus = await client.get("/api/admin/analytics/menus", headers=hdrs)
        assert menus.status_code == 200
        assert menus.json()["role"] == "sales_viewer"

    async def test_disabled_staff_cannot_login(self, client, auth):
        boss = await auth()
        invited = await client.post("/api/admin/analytics/staff", headers=boss, json={
            "email": "fired-e2e@aurora", "displayName": "离职E2E", "role": "sales_viewer",
        })
        staff_rows = (await client.get("/api/admin/analytics/staff", headers=boss)).json()["staff"]
        sid = next(s["id"] for s in staff_rows if s["email"] == "fired-e2e@aurora")
        await client.patch(f"/api/admin/analytics/staff/{sid}", headers=boss, json={"status": "disabled"})
        r = await client.post("/api/auth/login", json={"email": "fired-e2e@aurora", "password": DEV_PASSWORD})
        assert r.status_code == 401
        assert invited.status_code == 200

    async def test_customers_list(self, client, auth):
        boss = await auth()
        r = await client.get("/api/admin/analytics/customers", headers=boss)
        assert r.status_code == 200
        assert isinstance(r.json()["customers"], list)

    async def test_promotion_redeem_and_idempotency(self, client, auth):
        boss = await auth()
        created = await client.post("/api/admin/analytics/promotions", headers=boss, json={
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
                                headers=boss, json={"orderId": "NOT-EXIST"})
        assert bad.status_code == 400 and "不存在" in bad.json()["error"]
        # 种子订单 → 核销成功;重复 → 幂等拦截
        ok = await client.post(f"/api/admin/analytics/promotions/{pid}/redeem",
                               headers=boss, json={"orderId": "AURORA-ORD-2026-9081"})
        assert ok.status_code == 200 and ok.json()["discount"] > 0
        dup = await client.post(f"/api/admin/analytics/promotions/{pid}/redeem",
                                headers=boss, json={"orderId": "AURORA-ORD-2026-9081"})
        assert dup.status_code == 400 and "幂等" in dup.json()["error"]


class TestSkuCrud:
    """SKU 明细增删改查(承接 SPU 页展开;删除受成交护栏;prod:edit 权限点驱动)。"""

    async def test_sku_list_create_update_delete(self, client, auth):
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        spus = (await client.get("/api/admin/analytics/spus", headers=boss)).json()["spus"]
        spu_id = spus[0]["id"] if spus else None
        if not spu_id:
            pytest.skip("容器无 SPU 种子")

        created = await client.post(f"/api/admin/analytics/spus/{spu_id}/skus",
                                    headers=boss, json={"skuTitle": "E2E 规格", "price": 99.5, "stock": 7})
        assert created.status_code == 200
        code = created.json()["skuCode"]

        listed = await client.get(f"/api/admin/analytics/spus/{spu_id}/skus", headers=boss)
        assert any(s["sku_code"] == code for s in listed.json()["skus"])

        sku_id = next(s["id"] for s in listed.json()["skus"] if s["sku_code"] == code)
        patched = await client.patch(f"/api/admin/analytics/skus/{sku_id}", headers=boss,
                                     json={"price": 89.9, "stock": 5})
        assert patched.status_code == 200

        deleted = await client.delete(f"/api/admin/analytics/skus/{sku_id}", headers=boss)
        assert deleted.status_code == 200

    async def test_sku_stock_overview(self, client, auth):
        """SKU 库存总表(SKU 库存独立页数据源):跨 SPU 汇总并带商品标题。"""
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        r = await client.get("/api/admin/analytics/skus", headers=boss)
        assert r.status_code == 200
        skus = r.json()["skus"]
        assert isinstance(skus, list)
        if not skus:
            pytest.skip("容器无 SPU/SKU 种子")
        assert {"id", "sku_code", "spu_id", "spu_title", "price", "stock"} <= set(skus[0])

    async def test_sku_write_requires_prod_edit_perm(self, client, auth):
        """prod:edit 权限点:运营种子未勾选 → SKU 写操作 403(0013 动态派生)。"""
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        spus = (await client.get("/api/admin/analytics/spus", headers=boss)).json()["spus"]
        if not spus:
            pytest.skip("容器无 SPU 种子")
        ops = await auth("ops@aurora")
        r = await client.post(f"/api/admin/analytics/spus/{spus[0]['id']}/skus",
                              headers=ops, json={"skuTitle": "越权", "price": 1, "stock": 1})
        assert r.status_code == 403


class TestRegister:
    """商城用户注册(auth/register):建 engine 账号 + 客户档案联动 + 重复 409。"""

    async def test_register_success_and_login_roundtrip(self, client):
        import uuid as _uuid

        email = f"reg-{_uuid.uuid4().hex[:6]}@aurora.com"
        r = await client.post("/api/auth/register", json={
            "email": email, "password": "password123", "displayName": "E2E 用户",
        })
        assert r.status_code == 200, r.text
        body = r.json()["data"]
        assert body["user"]["email"] == email
        assert body["token"]
        assert body["user"]["customerId"].startswith("CUST-")

        # 注册后可登录(bcrypt 回读)
        login = await client.post("/api/auth/login", json={"email": email, "password": "password123"})
        assert login.status_code == 200 and login.json()["success"] is True

    async def test_duplicate_email_409(self, client):
        import uuid as _uuid

        email = f"dup-{_uuid.uuid4().hex[:6]}@aurora.com"
        first = await client.post("/api/auth/register", json={"email": email, "password": "password123"})
        assert first.status_code == 200
        dup = await client.post("/api/auth/register", json={"email": email, "password": "password456"})
        assert dup.status_code == 409 and "已注册" in dup.json()["message"]

    async def test_short_password_400(self, client):
        r = await client.post("/api/auth/register", json={"email": "x@y.com", "password": "123"})
        assert r.status_code == 400 and "8 位" in r.json()["message"]
