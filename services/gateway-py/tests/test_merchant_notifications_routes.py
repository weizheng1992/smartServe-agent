"""站内消息推送契约(mall-notifications 01,spec .scratch/mall-notifications):
员工侧发送 / 已发历史。钉死:鉴权两闸(无 JWT 401、无租户上下文 403)、perm
403、字段闸 400(标题/正文/长度/targetType)、定向顾客查无诚实 400、广播
频控(单员工单日 ≤20 业务错误)、历史形状(JOIN 顾客名 / 发送量快照 / 无回执
字段)。顾客侧与 SSE 由 02/03 票同文件追加。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from gateway_py.main import app

TENANT = {"x-tenant-id": "aurora"}
DEV_PASSWORD = "agent-all-dev"
E2E_CUSTOMER_ID = "CUST-E2E-NOTIF-1"


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture()
async def boss(client):
    from engine_py.analytics import rbac

    await rbac.ensure_defaults("aurora")
    r = await client.post("/api/auth/login", json={"email": "test@example.com", "password": DEV_PASSWORD})
    assert r.status_code == 200
    return {**TENANT, "Authorization": f"Bearer {r.json()['data']['token']}"}


async def _cleanup() -> None:
    """清本册痕迹(标题前缀 E2E-通知 / 临时顾客),不留跨用例污染。"""
    from engine_py.tools_registry.order_domain import _merchant_writer_engine

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    async with _merchant_writer_engine().begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM merchant_notification_reads WHERE notification_id IN "
                "(SELECT id FROM merchant_notifications WHERE title LIKE 'E2E-通知%')"
            )
        )
        await conn.execute(text("DELETE FROM merchant_notifications WHERE title LIKE 'E2E-通知%'"))
        await conn.execute(text("DELETE FROM merchant_customers WHERE customer_id LIKE 'CUST-E2E-NOTIF%'"))


async def _seed_customer() -> None:
    from engine_py.tools_registry.order_domain import _merchant_writer_engine

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    async with _merchant_writer_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO merchant_customers (customer_id, name, phone) "
                "VALUES (:cid, 'E2E通知顾客', '13800000000') "
                "ON CONFLICT (customer_id) DO NOTHING"
            ).bindparams(cid=E2E_CUSTOMER_ID)
        )


class TestAdminNotifications:
    async def test_send_requires_jwt(self, client):
        """无 JWT → 401(staff_context→require_claims 闸,HTTPException detail 形
        —— {success,error} 形是 resolve_bearer 特有,两形规则)。"""
        r = await client.post(
            "/api/admin/notifications",
            headers=TENANT,
            json={"targetType": "all", "title": "E2E-通知-x", "body": "x"},
        )
        assert r.status_code == 401
        assert "detail" in r.json()

    async def test_send_requires_tenant_context(self, client, boss):
        """有 JWT 无租户上下文 → 403(staff_context 统一 {"detail"} 形;
        复用 boss fixture 是为借 ensure_defaults 种员工,裸登录无员工行)。"""
        no_tenant = {k: v for k, v in boss.items() if k != "x-tenant-id"}
        r = await client.post(
            "/api/admin/notifications",
            headers=no_tenant,
            json={"targetType": "all", "title": "E2E-通知-x", "body": "x"},
        )
        assert r.status_code == 403

    async def test_send_field_gates(self, client, boss):
        """标题/正文必填与长度闸、targetType 闭集、定向缺 customerId。"""
        cases = [
            ({"targetType": "all", "title": "", "body": "x"}, "标题"),
            ({"targetType": "all", "title": "X" * 51, "body": "x"}, "标题"),
            ({"targetType": "all", "title": "E2E-通知-x", "body": "长" * 501}, "正文"),
            ({"targetType": "group", "title": "E2E-通知-x", "body": "x"}, "targetType"),
            ({"targetType": "customer", "title": "E2E-通知-x", "body": "x"}, "customerId"),
        ]
        for payload, keyword in cases:
            r = await client.post("/api/admin/notifications", headers=boss, json=payload)
            assert r.status_code == 400, f"{keyword} 闸未拦: {payload}"
            body = r.json()
            assert body["success"] is False and keyword in body["message"]

    async def test_send_target_customer_not_found(self, client, boss):
        """定向查无此顾客 → 400 诚实报错(幽灵单前置拦截同律)。"""
        try:
            r = await client.post(
                "/api/admin/notifications",
                headers=boss,
                json={"targetType": "customer", "customerId": "CUST-E2E-NOTIF-MISSING", "title": "E2E-通知-x", "body": "x"},
            )
            assert r.status_code == 400
            assert "不存在" in r.json()["message"]
        finally:
            await _cleanup()

    async def test_send_empty_body_ok(self, client, boss):
        """正文可留空(spec D2 只钉标题必填,F3 预设空正文合法态)。"""
        try:
            r = await client.post(
                "/api/admin/notifications",
                headers=boss,
                json={"targetType": "all", "title": "E2E-通知-空正文", "body": ""},
            )
            assert r.status_code == 200, r.text
            lst = await client.get("/api/admin/notifications", headers=boss)
            row = next(n for n in lst.json()["data"]["notifications"] if n["title"] == "E2E-通知-空正文")
            assert row["body"] == ""
        finally:
            await _cleanup()

    async def test_send_broadcast_and_list_shape(self, client, boss):
        """广播发送成功 → 历史列表出现(targetType=all / 发送量快照 / 无回执字段)。"""
        try:
            r = await client.post(
                "/api/admin/notifications",
                headers=boss,
                json={"targetType": "all", "title": "E2E-通知-广播", "body": "全店公告正文"},
            )
            assert r.status_code == 200, r.text
            data = r.json()["data"]
            assert data["targetType"] == "all"
            assert isinstance(data["recipientCount"], int)

            lst = await client.get("/api/admin/notifications", headers=boss)
            assert lst.status_code == 200
            page = lst.json()["data"]
            assert page["total"] >= 1
            row = next(n for n in page["notifications"] if n["title"] == "E2E-通知-广播")
            assert row["targetType"] == "all" and row["customerName"] is None
            assert row["recipientCount"] == data["recipientCount"]
            assert row["createdAt"].endswith("+00:00")  # aware UTC(两套钟律)
            for banned in ("readCount", "reads", "readReceipt"):
                assert banned not in row, f"商户历史不得携带回执字段: {banned}"
        finally:
            await _cleanup()

    async def test_send_targeted_with_customer_name(self, client, boss):
        """单客定向 → 列表行 JOIN 出顾客名;发送量恒 1。"""
        try:
            await _seed_customer()
            r = await client.post(
                "/api/admin/notifications",
                headers=boss,
                json={"targetType": "customer", "customerId": E2E_CUSTOMER_ID,
                      "title": "E2E-通知-定向", "body": "定向正文"},
            )
            assert r.status_code == 200, r.text
            assert r.json()["data"]["recipientCount"] == 1

            lst = await client.get("/api/admin/notifications", headers=boss)
            row = next(n for n in lst.json()["data"]["notifications"] if n["title"] == "E2E-通知-定向")
            assert row["customerId"] == E2E_CUSTOMER_ID
            assert row["customerName"] == "E2E通知顾客"
        finally:
            await _cleanup()

    async def test_broadcast_daily_limit(self, client, boss):
        """频控(单员工单日广播 ≤20):真实发送 1 次锚定 created_by,直插 19 条
        凑满,第 21 次业务错误 400「上限」。"""
        try:
            anchor = await client.post(
                "/api/admin/notifications",
                headers=boss,
                json={"targetType": "all", "title": "E2E-通知-限流锚", "body": "x"},
            )
            assert anchor.status_code == 200, anchor.text
            lst = await client.get("/api/admin/notifications", headers=boss)
            row = next(n for n in lst.json()["data"]["notifications"] if n["title"] == "E2E-通知-限流锚")
            created_by = row["createdBy"]

            from engine_py.tools_registry.order_domain import _merchant_writer_engine

            async with _merchant_writer_engine().begin() as conn:
                for i in range(19):
                    await conn.execute(
                        text(
                            "INSERT INTO merchant_notifications "
                            "(business_id, target_type, title, body, msg_type, recipient_count, created_by) "
                            "VALUES ('aurora', 'all', :title, 'x', 'announcement', 0, :by)"
                        ).bindparams(title=f"E2E-通知-填充{i}", by=created_by)
                    )

            r = await client.post(
                "/api/admin/notifications",
                headers=boss,
                json={"targetType": "all", "title": "E2E-通知-超限", "body": "x"},
            )
            assert r.status_code == 400
            assert "上限" in r.json()["message"]
        finally:
            await _cleanup()


async def _seed_store_rows() -> dict[str, str]:
    """直插三行(广播 / 我的定向 / 他客定向),返回 title→id;标题带 E2E-通知
    前缀共享 _cleanup 清扫。直插不走 boss API:02 的被测对象是店铺面读路径。"""
    from engine_py.tools_registry.order_domain import _merchant_writer_engine

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    out: dict[str, str] = {}
    async with _merchant_writer_engine().begin() as conn:
        for tt, cid, title in [
            ("all", None, "E2E-通知-店播"),
            ("customer", E2E_CUSTOMER_ID, "E2E-通知-我的定向"),
            ("customer", "CUST-E2E-NOTIF-OTHER", "E2E-通知-他客定向"),
        ]:
            out[title] = str(
                (
                    await conn.execute(
                        text(
                            "INSERT INTO merchant_notifications "
                            "(business_id, target_type, customer_id, title, body, msg_type, recipient_count, created_by) "
                            "VALUES ('aurora', :tt, :cid, :title, '正文', 'announcement', 1, 'staff_seed') "
                            "RETURNING id"
                        ).bindparams(tt=tt, cid=cid, title=title)
                    )
                ).scalar_one()
            )
    return out


class TestStoreNotifications:
    async def test_list_requires_user_id(self, client):
        """userId 必报(store/chat 配额闸同律:自报立约,缺省不冒领)。"""
        r = await client.get("/api/store/notifications")
        assert r.status_code == 400
        assert r.json()["success"] is False

    async def test_guest_honest_empty(self, client):
        """游客与非 CUST-* 身份四端点诚实空/零/空操作/拒连(spec F3 原文:按
        非 CUST-* 返回空且不入库 reads —— 不只挡 guest- 前缀;U2 律)。"""
        for uid in ("guest-e2e-notif", "user-not-cust"):
            r = await client.get("/api/store/notifications", params={"userId": uid})
            assert r.status_code == 200
            assert r.json()["data"]["notifications"] == [] and r.json()["data"]["total"] == 0

            r = await client.get("/api/store/notifications/unread-count", params={"userId": uid})
            assert r.json()["data"]["unread"] == 0

            r = await client.post(
                "/api/store/notifications/read", json={"userId": uid, "all": True}
            )
            assert r.status_code == 200 and r.json()["data"]["marked"] == 0

        r = await client.get(
            "/api/store/notifications/stream", params={"userId": "user-not-cust"}
        )
        assert r.status_code == 400

    async def test_visibility_and_read_flow(self, client):
        """属主闸 + 已读闭环:只见广播∪发给我的;未读数消减;标已读幂等;
        他客定向不可见。"""
        try:
            rows = await _seed_store_rows()
            uid = E2E_CUSTOMER_ID

            lst = await client.get("/api/store/notifications", params={"userId": uid})
            titles = [n["title"] for n in lst.json()["data"]["notifications"]]
            assert "E2E-通知-店播" in titles and "E2E-通知-我的定向" in titles
            assert "E2E-通知-他客定向" not in titles, "跨客定向泄漏(窃听族红线)"
            assert all(n["isRead"] is False for n in lst.json()["data"]["notifications"])

            r = await client.get("/api/store/notifications/unread-count", params={"userId": uid})
            assert r.json()["data"]["unread"] == 2

            r = await client.post(
                "/api/store/notifications/read",
                json={"userId": uid, "ids": [rows["E2E-通知-店播"]]},
            )
            assert r.json()["data"]["marked"] == 1
            r = await client.post(
                "/api/store/notifications/read",
                json={"userId": uid, "ids": [rows["E2E-通知-店播"]]},
            )
            assert r.json()["data"]["marked"] == 0, "标已读必须幂等"

            lst = await client.get("/api/store/notifications", params={"userId": uid})
            by_title = {n["title"]: n for n in lst.json()["data"]["notifications"]}
            assert by_title["E2E-通知-店播"]["isRead"] is True
            assert by_title["E2E-通知-我的定向"]["isRead"] is False

            r = await client.get("/api/store/notifications/unread-count", params={"userId": uid})
            assert r.json()["data"]["unread"] == 1

            r = await client.post("/api/store/notifications/read", json={"userId": uid, "all": True})
            assert r.json()["data"]["marked"] == 1
            r = await client.get("/api/store/notifications/unread-count", params={"userId": uid})
            assert r.json()["data"]["unread"] == 0
        finally:
            await _cleanup()

    async def test_cannot_mark_foreign_targeted(self, client):
        """跨客定向 id 混入 markRead → 静默 no-op(不报错不越权,可见性闸)。"""
        try:
            rows = await _seed_store_rows()
            uid = E2E_CUSTOMER_ID
            r = await client.post(
                "/api/store/notifications/read",
                json={"userId": uid, "ids": [rows["E2E-通知-他客定向"]]},
            )
            assert r.status_code == 200
            assert r.json()["data"]["marked"] == 0
            # 他客定向行零 reads 落库
            from engine_py.tools_registry.order_domain import _merchant_writer_engine

            async with _merchant_writer_engine().connect() as conn:
                cnt = (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM merchant_notification_reads "
                            "WHERE notification_id = CAST(:nid AS uuid)"
                        ).bindparams(nid=rows["E2E-通知-他客定向"])
                    )
                ).scalar_one()
            assert cnt == 0
        finally:
            await _cleanup()


class TestNotificationStream:
    async def test_stream_gates(self, client):
        """userId 必报 + 非 CUST-* 拒连(U2 律:无消息入口的身份不养连接)。"""
        r = await client.get("/api/store/notifications/stream")
        assert r.status_code == 400
        r = await client.get("/api/store/notifications/stream", params={"userId": "guest-e2e-notif"})
        assert r.status_code == 400
        assert "仅注册顾客" in r.json()["message"]

    async def test_signals_reach_stream(self, live_server):
        """真栈验证(live_server,SSE 需真网络栈):订阅就绪(connected 帧)后
        发布的三种信号帧均须到达 —— 广播帧、给我的定向帧、他客定向帧。

        第三条是**刻意钉死的 fan-in 契约**(03 裁决):服务端单频道转发不做
        per-connection 过滤(那要复制 tail_pubsub 泵或改公共语义,都不值),
        帧零消息内容,过滤在前端。此断言防止未来静默改成服务端过滤或漏转发。
        顺序纪律:pubsub 无重放,必须等 connected 帧后再发布(镜像顾客端
        EventSource 常驻先挂的真实时序)。"""
        import httpx as _httpx
        from engine_py.event_bus import get_client

        redis = await get_client()
        assert redis is not None, "测试容器 Redis 未就绪"

        timeout = _httpx.Timeout(10.0, read=20.0)
        raw = ""
        sent = False
        async with _httpx.AsyncClient(base_url=live_server, timeout=timeout) as hc, hc.stream(
            "GET", "/api/store/notifications/stream?userId=CUST-E2E-NOTIF-1&businessId=aurora"
        ) as res:
            assert res.status_code == 200
            async for chunk in res.aiter_text():
                raw += chunk
                if not sent and "event: connected" in raw:
                    sent = True
                    await redis.publish(
                        "notify:business:aurora",
                        '{"type": "notification", "marker": "broadcast-sig"}',
                    )
                    await redis.publish(
                        "notify:business:aurora",
                        '{"type": "notification", "targetUserId": "CUST-E2E-NOTIF-1", "marker": "mine-sig"}',
                    )
                    await redis.publish(
                        "notify:business:aurora",
                        '{"type": "notification", "targetUserId": "CUST-E2E-NOTIF-OTHER", "marker": "foreign-sig"}',
                    )
                if sent and "foreign-sig" in raw:
                    break

        assert sent, "SSE 流未就绪(connected 帧未到)"
        for marker in ("broadcast-sig", "mine-sig", "foreign-sig"):
            assert marker in raw, f"信号帧未达: {marker}; 流尾: {raw[-400:]}"
