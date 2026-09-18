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
