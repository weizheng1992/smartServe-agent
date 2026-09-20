"""商户 data agent 路由契约(阶段④;/api/admin/analytics/*;0013 JWT 收口)。

覆盖:JWT 身份(无 token 401/未知员工 403)、ask(SSE 四事件形态/越权指标拒绝/
无问题 400)、menus(RBAC 角色过滤 + 种子幂等 + 仓储菜单收敛)、roles 分配(非老板
403/老板保存生效/勾选即生效的按钮权限授予与回收)、staff 列表与老板签发切换、
reports(生成/列表/详情/CSV;report:gen 权限点驱动)、促销(perm 驱动)。
"""

from __future__ import annotations

import json
import os
import uuid

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


@pytest.fixture()
def patch_embedding(monkeypatch):
    """密封 L2 范例向量:CI 无 bge 权重缓存且 hf-mirror 不可达(2026-09-20 实证)。

    exemplar_service 走 graph.ask 的 L2 回放(UnsupportedQuery 被 search_exemplar
    吞掉放行),靠异常兜底不算密封 —— ask 面用例统一桩掉模型加载。
    按问题文本哈希生成 one-hot 向量:同问相似度 1.0(回放命中),异问不串扰
    (不会误中其他用例登记的范例)。
    """
    import hashlib

    class _FakeEmbed:
        async def aembed_query(self, text: str) -> list[float]:
            idx = int(hashlib.md5(text.encode()).hexdigest(), 16) % 64
            return [1.0 if i == idx else 0.0 for i in range(64)]

    monkeypatch.setattr("engine_py.llm.get_embedding_model", lambda: _FakeEmbed())


class TestAsk:
    async def test_ask_selected_orders_compare(self, client, auth):
        """PageContext 勾选两单 → 「两个订单对比」出逐笔行 + 合计/均值(ADR-0005)。"""
        from engine_py.tools_registry.order_domain import _merchant_writer_engine
        from sqlalchemy import text as _t

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        async with _merchant_writer_engine().begin() as c:
            for oid, amt in (("E2E-CMP-A", 300.00), ("E2E-CMP-B", 500.00)):
                await c.execute(_t(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, shipping_address) "
                    "VALUES (:oid, 'CUST-CMP', 'PAID', :amt, '{}'::jsonb) "
                    "ON CONFLICT (order_id) DO UPDATE SET total_amount = :amt, status = 'PAID'"
                ), {"oid": oid, "amt": amt})

        r = await client.post("/api/admin/analytics/ask", headers=boss, json={
            "question": "两个订单对比",
            "pageContext": {"selection": ["E2E-CMP-A", "E2E-CMP-B"]},
        })
        events = dict(_sse_events(r))
        assert events["result"]["metric"] == "order_overview"
        rows = events["result"]["rows"]
        assert {row["订单号"] for row in rows} == {"E2E-CMP-A", "E2E-CMP-B"}
        assert all("合计金额" in row and "平均金额" in row for row in rows)

    async def test_ask_unsupported_is_honest(self, client, auth, patch_embedding):
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


class TestL3AndGrowth:
    """ADR-0005:L3 意图兜底 / 实体反问 / L2 范例回放 / 未命中落库 / 角色防线。

    L3 的 LLM 调用在测试中 monkeypatch(外部服务);数据全部走密封真实库。
    """

    @pytest.fixture()
    def patch_llm(self, monkeypatch):
        """替换 llm_resolve:返回预定意图/clarify,便于隔离测 graph 接线。"""
        def _patch(outcome):
            async def _fake(question, allowed=None, business_id=""):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            monkeypatch.setattr("engine_py.analytics.llm_intent.llm_resolve", _fake)
        return _patch


    async def test_l3_activity_effect_sse(self, client, auth, patch_llm, patch_embedding):
        from engine_py.analytics.engine import StructuredQueryIntent
        from engine_py.tools_registry.order_domain import _merchant_writer_engine
        from sqlalchemy import text as _t

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        created = await client.post("/api/admin/analytics/promotions", headers=boss, json={
            "name": "E2E L3 活动效果", "promoType": "full_reduction", "threshold": 100, "value": 10,
        })
        pid = created.json()["id"]

        # 种核销归因:活动 → 真实订单
        async with _merchant_writer_engine().begin() as conn:
            await conn.execute(_t(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, shipping_address) "
                "VALUES ('E2E-L3-ORD', 'CUST-L3', 'PAID', 500.00, '{}'::jsonb) "
                "ON CONFLICT (order_id) DO UPDATE SET total_amount = 500.00"
            ))
            await conn.execute(_t(
                "INSERT INTO promotion_redemptions (promotion_id, order_id, discount_amount) "
                "VALUES (CAST(:p AS uuid), 'E2E-L3-ORD', 10.00)"
            ).bindparams(p=pid))

        patch_llm(StructuredQueryIntent(
            metric="promo_effect", entity_slot={"promotion": [pid]},
        ))
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": "E2E L3 那档子促销战报如何"})
        events = dict(_sse_events(r))
        assert events["result"]["metric"] == "promo_effect"
        row = events["result"]["rows"][0]
        assert row["核销订单数"] >= 1 and row["优惠总额"] >= 10

    async def test_l3_customer_orders_sse(self, client, auth, patch_llm, patch_embedding):
        from engine_py.analytics.engine import StructuredQueryIntent

        boss = await auth()
        patch_llm(StructuredQueryIntent(
            metric="customer_orders", entity_slot={"customer": ["CUST-L3"]}, limit=10,
        ))
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": "L3 客户最近的订单"})
        events = dict(_sse_events(r))
        assert events["result"]["metric"] == "customer_orders"
        assert isinstance(events["result"]["rows"], list)

    async def test_entity_clarify_multi_hit_and_reply_loop(self, client, auth, patch_llm, patch_embedding):
        """多命中 → clarify(entity) → 按选项原词回问 → 唯一命中出结果(闭环)。"""
        from engine_py.analytics.engine import StructuredQueryIntent
        from engine_py.analytics.llm_intent import _EntityClarify

        boss = await auth()
        await client.post("/api/admin/analytics/promotions", headers=boss, json={
            "name": "E2E 多命中活动甲", "promoType": "coupon", "value": 5,
        })
        await client.post("/api/admin/analytics/promotions", headers=boss, json={
            "name": "E2E 多命中活动乙", "promoType": "coupon", "value": 8,
        })

        patch_llm(_EntityClarify("promotion", [
            {"id": "id-甲", "label": "E2E 多命中活动甲"},
            {"id": "id-乙", "label": "E2E 多命中活动乙"},
        ], "多命中活动卖得怎么样"))
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": "多命中活动卖得怎么样"})
        events = dict(_sse_events(r))
        assert events["clarify"]["clarifyKind"] == "entity"
        labels = [o["label"] for o in events["clarify"]["options"]]
        assert "E2E 多命中活动甲" in labels

        # 回问闭环:用户点选后原词回问 → L3 唯一解析 → 出结果
        target = next(p for p in
                      (await client.get("/api/admin/analytics/promotions", headers=boss)).json()["promotions"]
                      if p["name"] == "E2E 多命中活动甲")
        patch_llm(StructuredQueryIntent(
            metric="promo_effect", entity_slot={"promotion": [target["id"]]},
        ))
        r2 = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": "E2E 多命中活动甲"})
        events2 = dict(_sse_events(r2))
        assert events2["result"]["metric"] == "promo_effect"

    async def test_exemplar_replay_l2(self, client, auth, patch_embedding):
        """L2 范例回放:L0 未命中的问句,登记范例后同问直出意图(不触 L3)。"""
        from engine_py.analytics import exemplar_service

        question = "E2E 范例回放专用神秘问法"
        await exemplar_service.add_exemplar(
            "aurora", question,
            {"metric": "gmv", "direction": "DESC", "limit": 5, "time_window": None, "category": None},
            source="llm",
        )
        boss = await auth()
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": question})
        events = dict(_sse_events(r))
        assert events["result"]["metric"] == "gmv"

    async def test_unsupported_logged_to_agent_unanswered(self, client, auth):
        import uuid

        from engine_py.db import AgentUnanswered, get_session
        from sqlalchemy import select

        question = f"E2E 宇宙语问题 {uuid.uuid4().hex[:8]}"
        boss = await auth()
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": question})
        assert dict(_sse_events(r)).get("unsupported")
        async with get_session() as session:
            rows = (await session.execute(
                select(AgentUnanswered).where(AgentUnanswered.question == question)
            )).scalars().all()
        assert len(rows) == 1 and rows[0].role == "finance_owner"

    async def test_clarify_options_filtered_by_role(self, client, auth):
        """仓储视角泛指问句 → clarify 选项收敛到其指标闭集(13 号票欠账)。"""
        boss = await auth()
        sw = await client.post("/api/admin/analytics/staff/switch", headers=boss, json={"staffId": "wh@aurora"})
        wh = {**TENANT, "Authorization": f"Bearer {sw.json()['token']}"}
        r = await client.post("/api/admin/analytics/ask", headers=wh, json={"question": "卖得最好的商品"})
        events = dict(_sse_events(r))
        options = events["clarify"]["options"]
        assert options, "仓储闭集内应有可反问的兄弟指标"
        assert all(o["key"] in ("volume", "stock_risk") for o in options)

    async def test_stale_exemplar_deactivated_and_falls_to_l3(self, client, auth, patch_llm, patch_embedding, monkeypatch):
        """L2 范例指向已删除实体 → 停用范例并落 L3(ADR-0005 后续①)。"""
        from engine_py.analytics import exemplar_service
        from engine_py.analytics.engine import StructuredQueryIntent

        question = f"E2E 陈旧范例回放问法 {uuid.uuid4().hex[:8]}"
        # 范例指向一个不存在的活动
        await exemplar_service.add_exemplar(
            "aurora", question,
            {"metric": "gmv", "direction": "DESC", "limit": 5, "time_window": None,
             "category": None, "entity_slot": {"promotion": ["00000000-0000-0000-0000-000000000000"]}},
            source="llm",
        )
        called = {"n": 0}

        async def _fake_llm(q, allowed=None, business_id=""):
            called["n"] += 1
            return StructuredQueryIntent(metric="gmv", direction="DESC", limit=5)

        monkeypatch.setattr("engine_py.analytics.llm_intent.llm_resolve", _fake_llm)

        boss = await auth()
        r = await client.post("/api/admin/analytics/ask", headers=boss, json={"question": question})
        events = dict(_sse_events(r))
        assert events["result"]["metric"] == "gmv"
        assert called["n"] == 1, "陈旧范例应落 L3(被调用)"
        # 范例已停用,不会再次劫持
        rows = await exemplar_service.search_exemplar(question, "aurora")
        assert rows is None

    async def test_admin_can_manage(self, client, auth):
        """0014+:admin 管理员角色可分配权限/管理菜单/切换身份(老板之外的第二管理角色)。"""
        from engine_py.analytics import rbac

        await rbac.ensure_defaults("aurora")
        admin = await auth("admin@aurora")

        # ① 勾选菜单分配权限保存成功
        base = (await client.get("/api/admin/analytics/roles/warehouse_operator/menus", headers=admin)).json()["menuIds"]
        ok = await client.post("/api/admin/analytics/roles/warehouse_operator/menus",
                               headers=admin, json={"menuIds": base})
        assert ok.status_code == 200

        # ② 新建菜单成功(管理菜单闸)
        created = await client.post("/api/admin/analytics/menus", headers=admin, json={
            "name": "管理员建菜单", "menuType": "menu", "route": "/admin-tmp",
        })
        assert created.status_code == 200
        await client.delete(f"/api/admin/analytics/menus/{created.json()['id']}", headers=admin)

        # ③ 切换身份成功
        sw = await client.post("/api/admin/analytics/staff/switch", headers=admin, json={"staffId": "wh@aurora"})
        assert sw.status_code == 200 and sw.json()["role"] == "warehouse_operator"

    def test_admin_seed_metrics_full(self):
        """管理员指标闭集 = 全量(纯配置断言;零 DB/零 loop,防跨 loop 连接池冲突)。"""
        from engine_py.analytics.rbac import (
            MANAGER_ROLES,
            ROLE_METRIC_PERMISSIONS,
            is_manager,
        )

        assert ROLE_METRIC_PERMISSIONS["admin"] is None
        assert "admin" in MANAGER_ROLES and is_manager("admin")
        assert not is_manager("sales_viewer")

    async def test_promo_compare_sse(self, client, auth, patch_llm, monkeypatch):
        """双活动对比查询族(ADR-0005 登记流水线首批):L3 解析双实体 → 并排两行。"""
        from engine_py.analytics.engine import StructuredQueryIntent
        from engine_py.tools_registry.order_domain import _merchant_writer_engine
        from sqlalchemy import text as _t

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        boss = await auth()
        pa = await client.post("/api/admin/analytics/promotions", headers=boss, json={
            "name": "E2E 对比活动A", "promoType": "full_reduction", "threshold": 100, "value": 20})
        pb = await client.post("/api/admin/analytics/promotions", headers=boss, json={
            "name": "E2E 对比活动B", "promoType": "full_reduction", "threshold": 200, "value": 40})
        ida, idb = pa.json()["id"], pb.json()["id"]

        async with _merchant_writer_engine().begin() as conn:
            for oid, cid, amt in (("E2E-CMP2-A", "C1", 400.00), ("E2E-CMP2-B", "C2", 800.00)):
                await conn.execute(_t(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, shipping_address) "
                    "VALUES (:oid, :cid, 'PAID', :amt, '{}'::jsonb) "
                    "ON CONFLICT (order_id) DO UPDATE SET total_amount = :amt"
                ), {"oid": oid, "cid": cid, "amt": amt})
            await conn.execute(_t(
                "INSERT INTO promotion_redemptions (promotion_id, order_id, discount_amount) "
                "VALUES (CAST(:a AS uuid), 'E2E-CMP2-A', 20.00), (CAST(:b AS uuid), 'E2E-CMP2-B', 40.00)"
            ), {"a": ida, "b": idb})

        async def _fake_llm(q, allowed=None, business_id=""):
            return StructuredQueryIntent(
                metric="promo_compare", entity_slot={"promotion": [ida, idb]},
            )
        monkeypatch.setattr("engine_py.analytics.llm_intent.llm_resolve", _fake_llm)

        r = await client.post("/api/admin/analytics/ask", headers=boss, json={
            "question": "E2E 对比活动A 和 E2E 对比活动B 哪个好",
        })
        events = dict(_sse_events(r))
        assert events["result"]["metric"] == "promo_compare"
        rows = events["result"]["rows"]
        assert len(rows) == 2
        assert all("核销订单数" in row and "核销GMV" in row for row in rows)

        # 清理
        async with _merchant_writer_engine().begin() as conn:
            await conn.execute(_t("DELETE FROM promotion_redemptions WHERE order_id LIKE 'E2E-CMP2-%'"))
            await conn.execute(_t("DELETE FROM merchant_orders WHERE order_id LIKE 'E2E-CMP2-%'"))
            await conn.execute(_t("DELETE FROM promotions WHERE id IN (CAST(:a AS uuid), CAST(:b AS uuid))"),
                               {"a": ida, "b": idb})

    async def test_ship_rbac(self, client, auth):
        """发货(order:ship)RBAC:无 token 401 / 运营 403 / 仓储过闸到业务校验。"""
        boss = await auth()
        body = {"orderId": "E2E 不存在的单", "trackingNo": "SF123"}

        r_none = await client.post("/api/admin/orders/ship", json=body)
        assert r_none.status_code == 401

        # 运营(无 order:ship 权限点)→ 403
        ops = await auth("ops@aurora")
        r_ops = await client.post("/api/admin/orders/ship", headers=ops, json=body)
        assert r_ops.status_code == 403

        # 仓储(有 order:ship)过权限闸,未命中业务校验前不落库:订单不存在 → 诚实报错
        sw = await client.post("/api/admin/analytics/staff/switch", headers=boss, json={"staffId": "wh@aurora"})
        wh = {"x-tenant-id": "aurora", "Authorization": f"Bearer {sw.json()['token']}"}
        r_wh = await client.post("/api/admin/orders/ship", headers=wh, json=body)
        assert r_wh.json().get("success") is False

        # 老板缺字段 → 400 参数校验
        r_boss = await client.post("/api/admin/orders/ship", headers=boss, json={"orderId": "x"})
        assert r_boss.status_code == 400

    async def test_ship_rbac_cross_tenant(self, client, auth):
        """他租员工不得按 aurora 菜单放行(2026-09-20 review:perms 硬编码 aurora 假租户)。"""
        from engine_py.db import StaffMember, get_session
        from sqlalchemy import delete, select

        await auth()  # ensure_defaults(aurora) 先行,拿到种子 bcrypt 哈希
        async with get_session() as session:
            src = (await session.execute(
                select(StaffMember).where(StaffMember.id == "staff_wh")
            )).scalars().first()
            session.add(StaffMember(
                id="staff_nike_wh", business_id="nike", email="wh@nike",
                display_name="仓储N", role="warehouse_operator", status="enabled",
                password_hash=src.password_hash,
            ))
            await session.commit()
        try:
            r = await client.post("/api/auth/login", json={"email": "wh@nike", "password": DEV_PASSWORD})
            assert r.status_code == 200
            token = r.json()["data"]["token"]
            r_ship = await client.post(
                "/api/admin/orders/ship",
                headers={"x-tenant-id": "nike", "Authorization": f"Bearer {token}"},
                json={"orderId": "x", "trackingNo": "SF1"},
            )
            # nike 未配置任何角色菜单 → order:ship 闭集为空 → 403(而非借 aurora 菜单放行)
            assert r_ship.status_code == 403
            assert "无发货权限" in r_ship.json()["message"]
        finally:
            async with get_session() as session:
                await session.execute(delete(StaffMember).where(StaffMember.id == "staff_nike_wh"))
                await session.commit()

    async def test_fallback_rechecks_role_403(self, client, auth, patch_llm):
        """防御纵深:resolver 被替换时,兜底结果仍过角色闭集,越权 → unsupported。"""
        from engine_py.analytics.engine import StructuredQueryIntent

        ops = await auth("ops@aurora")  # 运营闭集不含 gross_profit
        patch_llm(StructuredQueryIntent(metric="gross_profit", direction="DESC"))
        # 问法避开 L0 词表 → 走兜底 → 纵深校验拦截
        r = await client.post("/api/admin/analytics/ask", headers=ops, json={"question": "上季度利润贡献王者榜单"})
        events = dict(_sse_events(r))
        assert events["unsupported"]["message"] == "当前角色无权查看该指标"


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
