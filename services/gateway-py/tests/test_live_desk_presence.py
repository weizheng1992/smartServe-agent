"""P2 坐席在线态与 perm 闸契约(live-desk-rework spec §3 P2 行)。

① presence 单元语义:心跳即在线;TTL 过期即离线(读取侧 score 比较 + 修剪);
   drop 即离线;免打扰 SET 开关无 TTL、可复位。
② socket 接线:operator 连接即点亮 presence,断开即熄灭(单连接假设)。
③ HTTP 路由:GET /api/merchant/live-desk/presence(员工行 ⨝ presence,匿名
   401)、POST /api/merchant/live-desk/presence/dnd 自拨开关。
④ perms 三态:finance_owner 全量、sales_viewer 恰持 operate、
   warehouse_operator 无 → 403。

presence 键按租户命名空间 —— 各用例用一次性租户串避免互相污染。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from engine_py.approvals import presence

from .conftest import _TS

pytestmark = pytest.mark.usefixtures("seeded")

STAFF_EMAIL = "test@example.com"  # staff_auth = aurora finance_owner


def _tenant() -> str:
    return f"pa_{_TS}_{uuid.uuid4().hex[:6]}"


def _auth_headers(staff_id: str, email: str) -> dict:
    from gateway_py.routers.auth import issue_token

    return {"Authorization": f"Bearer {issue_token(staff_id, email)}"}


class TestPresenceUnit:
    async def test_心跳即在线_免打扰默认关(self):
        tenant = _tenant()
        await presence.heartbeat(tenant, "a@x.test")
        pmap = await presence.presence_map(tenant)
        assert pmap["a@x.test"]["online"] is True
        assert pmap["a@x.test"]["dnd"] is False
        assert pmap["a@x.test"]["lastSeenAt"]

    async def test_TTL过期即离线(self):
        tenant = _tenant()
        await presence.heartbeat(tenant, "a@x.test")
        # ttl=0:读取侧 score 比较判过期并顺手修剪 —— 不用真实 sleep
        pmap = await presence.presence_map(tenant, ttl_seconds=0.0)
        assert not pmap.get("a@x.test", {}).get("online")

    async def test_drop即离线(self):
        tenant = _tenant()
        await presence.heartbeat(tenant, "a@x.test")
        await presence.drop(tenant, "a@x.test")
        assert "a@x.test" not in await presence.presence_map(tenant)

    async def test_免打扰开关可复位(self):
        tenant = _tenant()
        await presence.set_dnd(tenant, "a@x.test", True)
        assert (await presence.presence_map(tenant))["a@x.test"]["dnd"] is True
        await presence.set_dnd(tenant, "a@x.test", False)
        # 复位后既不在线也无免打扰 → 成员从汇总消失(汇总 = 在线 ∪ 免打扰)
        assert "a@x.test" not in await presence.presence_map(tenant)


class TestPresenceSocketWiring:
    async def test_operator连接即在线_断开即离线(self, live_server, nike_operator):
        import socketio as socketio_lib

        ns = "/ws/chat"
        c = socketio_lib.AsyncClient(reconnection=False)
        await c.connect(
            live_server, transports=["websocket"], namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_pa", "role": "operator", "token": nike_operator["token"]},
        )
        pmap = await presence.presence_map("nike")
        assert pmap.get(nike_operator["email"], {}).get("online") is True
        await c.disconnect()
        deadline = asyncio.get_event_loop().time() + 3
        while asyncio.get_event_loop().time() < deadline:
            if nike_operator["email"] not in await presence.presence_map("nike"):
                break
            await asyncio.sleep(0.05)
        assert nike_operator["email"] not in await presence.presence_map("nike")


class TestPresenceRoutes:
    async def test_员工读在线态_含自己且字段齐(self, client, staff_auth):
        from engine_py.analytics import rbac

        await rbac.ensure_defaults("aurora")
        await presence.heartbeat("aurora", STAFF_EMAIL)
        res = await client.get("/api/merchant/live-desk/presence", headers=staff_auth)
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert body["tenantId"] == "aurora"
        row = next(a for a in body["agents"] if a["email"] == STAFF_EMAIL)
        assert row["online"] is True and row["dnd"] is False and row["lastSeenAt"]
        for key in ("email", "name", "role", "online", "dnd", "lastSeenAt"):
            assert key in row

    async def test_匿名读在线态_401(self, client):
        res = await client.get("/api/merchant/live-desk/presence")
        assert res.status_code == 401

    async def test_免打扰自拨开关(self, client, staff_auth):
        res = await client.post("/api/merchant/live-desk/presence/dnd", headers=staff_auth, json={"enabled": True})
        assert res.status_code == 200
        assert res.json()["dnd"] is True
        pmap = await presence.presence_map("aurora")
        assert pmap[STAFF_EMAIL]["dnd"] is True
        # 复位,不留状态给其他用例
        res = await client.post("/api/merchant/live-desk/presence/dnd", headers=staff_auth, json={"enabled": False})
        assert res.json()["dnd"] is False

    async def test_warehouse无operate_403(self, client):
        """warehouse_operator 角色菜单闭包无 live_desk:operate → 403。"""
        from engine_py.analytics import rbac
        from engine_py.db import StaffMember, get_session


        await rbac.ensure_defaults("aurora")
        sid, email = f"staff_pa_wh_{_TS}", f"wh_{_TS}@aurora.test"
        async with get_session() as session:
            session.add(StaffMember(
                id=sid, business_id="aurora", email=email,
                display_name="仓储员", role="warehouse_operator", status="enabled", password_hash=None,
            ))
            await session.commit()
        res = await client.get("/api/merchant/live-desk/presence", headers=_auth_headers(sid, email))
        assert res.status_code == 403
        assert res.json()["success"] is False

    async def test_salesviewer持operate_200_finance_owner全量(self, client, staff_auth):
        """sales_viewer 不灰度排除 operate 按钮(P1 旧 tab 既有持有者)→ 200;
        finance_owner 兜底全量(staff_auth 同例)→ 200。"""
        from engine_py.analytics import rbac
        from engine_py.db import StaffMember, get_session


        await rbac.ensure_defaults("aurora")
        assert "live_desk:operate" in await rbac.perms_for_role("aurora", "sales_viewer")
        sid, email = f"staff_pa_sv_{_TS}", f"sv_{_TS}@aurora.test"
        async with get_session() as session:
            session.add(StaffMember(
                id=sid, business_id="aurora", email=email,
                display_name="销售员", role="sales_viewer", status="enabled", password_hash=None,
            ))
            await session.commit()
        res = await client.get("/api/merchant/live-desk/presence", headers=_auth_headers(sid, email))
        assert res.status_code == 200
        assert res.json()["success"] is True
        # finance_owner(staff_auth)全量兜底
        assert "live_desk:operate" in await rbac.perms_for_role("aurora", "finance_owner")
