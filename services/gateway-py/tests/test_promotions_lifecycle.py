"""优惠活动运营闭环契约(2026-09-27):时间窗全链路 + 券发放量控 + 窗口外核销拒绝。

钉死:创建带窗(过 end → effectiveStatus=ended;未来 start → scheduled;无窗 →
running)、窗口非法 400、PATCH 改窗(engine update_promotion 单一实现;坏窗 400 /
不存在 404)、券发放上限(上限 2 第 3 张 400「上限」)、过期活动补录核销拒绝。
结算侧窗口闸(fetch_active_promos 未来 start 不进候选)由 engine-py
tests/test_promotion_engine.py 钉死,两侧同口径。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from gateway_py.main import app

TENANT = {"x-tenant-id": "aurora"}
DEV_PASSWORD = "agent-all-dev"


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


async def _cleanup(promo_ids: list[str]) -> None:
    """清干净本册产生的活动与关联行(券/核销),不留跨用例污染。"""
    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    async with _merchant_writer_engine().begin() as conn:
        for pid in promo_ids:
            await conn.execute(
                text("DELETE FROM user_coupons WHERE promotion_id = CAST(:id AS uuid)").bindparams(id=pid)
            )
            await conn.execute(
                text("DELETE FROM promotion_redemptions WHERE promotion_id = CAST(:id AS uuid)").bindparams(id=pid)
            )
            await conn.execute(
                text("DELETE FROM promotions WHERE id = CAST(:id AS uuid)").bindparams(id=pid)
            )


class TestPromotionsLifecycle:
    async def _create(self, client, boss, name: str, promo_type: str, **fields) -> dict:
        r = await client.post(
            "/api/admin/analytics/promotions",
            headers=boss,
            json={"name": name, "promoType": promo_type, **fields},
        )
        assert r.status_code == 200, r.text
        return r.json()

    async def _listed_by_id(self, client, boss) -> dict[str, dict]:
        r = await client.get("/api/admin/analytics/promotions", headers=boss)
        assert r.status_code == 200
        return {p["id"]: p for p in r.json()["promotions"]}

    async def test_window_create_effective_status(self, client, boss):
        """时间窗创建 → 服务端派生 effectiveStatus 四态(前端不自行算);
        列表行同时带出量控/效果扩展字段(payload 扩展契约)。"""
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        now = datetime.now()
        ended = await self._create(client, boss, "E2E 窗-已结束", "full_reduction",
                                   threshold=100, value=10,
                                   startAt=(now - timedelta(days=2)).isoformat(),
                                   endAt=(now - timedelta(days=1)).isoformat())
        scheduled = await self._create(client, boss, "E2E 窗-未开始", "full_reduction",
                                       threshold=100, value=10,
                                       startAt=(now + timedelta(days=1)).isoformat())
        running = await self._create(client, boss, "E2E 窗-进行中", "full_reduction",
                                     threshold=100, value=10)
        try:
            by_id = await self._listed_by_id(client, boss)
            assert by_id[ended["id"]]["effectiveStatus"] == "ended"
            assert by_id[scheduled["id"]]["effectiveStatus"] == "scheduled"
            assert by_id[running["id"]]["effectiveStatus"] == "running"
            # 三态下 status 仍为 active(手工启停语义与生效态解耦)
            assert all(by_id[i]["status"] == "active" for i in (ended["id"], scheduled["id"], running["id"]))
            row = by_id[running["id"]]
            for key in ("totalQuota", "claimedCount", "usedCount", "redemptionCount", "discountTotal"):
                assert key in row, f"列表扩展字段缺 {key}"
            assert row["claimedCount"] == 0 and row["redemptionCount"] == 0
        finally:
            await _cleanup([ended["id"], scheduled["id"], running["id"]])

    async def test_bad_window_rejected_400(self, client, boss):
        now = datetime.now()
        r = await client.post(
            "/api/admin/analytics/promotions",
            headers=boss,
            json={
                "name": "E2E 坏窗", "promoType": "full_reduction", "value": 10,
                "startAt": now.isoformat(), "endAt": (now - timedelta(hours=1)).isoformat(),
            },
        )
        assert r.status_code == 400
        assert "结束时间" in r.json()["error"]

    async def test_patch_updates_window_and_validates(self, client, boss):
        """PATCH 改窗生效(下沉 engine update_promotion);坏窗 400;不存在 404。"""
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        created = await self._create(client, boss, "E2E 改窗", "full_reduction", threshold=100, value=10)
        # 造数钟与被测比较钟同源:服务端窗口比较走 UTC 库钟(_utcnow /
        # SQL NOW(),2026-09-29 F15 复核),-5min 边际吃不下本地钟的时区偏移;
        # naive 输入(前端 datetime-local)的口径另票处理。
        now = datetime.now(UTC).replace(tzinfo=None)
        try:
            patched = await client.patch(
                f"/api/admin/analytics/promotions/{created['id']}",
                headers=boss,
                # 起点同步挪到过去:start_at 缺省 = 创建时刻(SQL NOW()),UTC
                # 纯净语义下「end 早于 start 5min」本就是坏窗(旧造数靠本地钟
                # 8h 时差才碰巧合法);起点终点一起改才是真实的「改为已过期」。
                json={
                    "startAt": (now - timedelta(days=2)).isoformat(),
                    "endAt": (now - timedelta(minutes=5)).isoformat(),
                },
            )
            assert patched.status_code == 200, patched.text
            by_id = await self._listed_by_id(client, boss)
            assert by_id[created["id"]]["effectiveStatus"] == "ended"
            assert by_id[created["id"]]["endAt"] is not None

            # 改回未来开始 → scheduled(单改一端与库内另一端合判,不误伤)
            future_start = (now + timedelta(days=1)).isoformat()
            repatched = await client.patch(
                f"/api/admin/analytics/promotions/{created['id']}",
                headers=boss,
                json={"startAt": future_start, "endAt": (now + timedelta(days=2)).isoformat()},
            )
            assert repatched.status_code == 200
            by_id = await self._listed_by_id(client, boss)
            assert by_id[created["id"]]["effectiveStatus"] == "scheduled"

            bad = await client.patch(
                f"/api/admin/analytics/promotions/{created['id']}",
                headers=boss,
                json={"endAt": (now - timedelta(days=1)).isoformat()},
            )
            assert bad.status_code == 400  # 合并后 end < 库内 start → 坏窗

            missing = await client.patch(
                "/api/admin/analytics/promotions/00000000-0000-0000-0000-000000000000",
                headers=boss,
                json={"name": "x"},
            )
            assert missing.status_code == 404
        finally:
            await _cleanup([created["id"]])

    async def test_coupon_quota_gate_third_grant_400(self, client, boss):
        """发放上限量控:上限 2 → 前两张成功,第 3 张 400「上限」;列表已领数回真。"""
        from engine_py.tools_registry.order_domain import _merchant_writer_engine
        from sqlalchemy import text

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        async with _merchant_writer_engine().begin() as conn:
            for cid in ("CUST-QT-1", "CUST-QT-2", "CUST-QT-3"):
                await conn.execute(text(
                    "INSERT INTO merchant_customers (customer_id, name, phone) "
                    "VALUES (:cid, '量控对象', '13800000001') "
                    "ON CONFLICT (customer_id) DO NOTHING"
                ).bindparams(cid=cid))

        created = await self._create(client, boss, "E2E 量控券", "coupon", value=20, totalQuota=2)
        try:
            first = await client.post(f"/api/admin/analytics/promotions/{created['id']}/grant",
                                      headers=boss, json={"customerId": "CUST-QT-1"})
            assert first.status_code == 200
            second = await client.post(f"/api/admin/analytics/promotions/{created['id']}/grant",
                                       headers=boss, json={"customerId": "CUST-QT-2"})
            assert second.status_code == 200
            third = await client.post(f"/api/admin/analytics/promotions/{created['id']}/grant",
                                      headers=boss, json={"customerId": "CUST-QT-3"})
            assert third.status_code == 400
            assert "上限" in third.json()["error"]

            by_id = await self._listed_by_id(client, boss)
            assert by_id[created["id"]]["totalQuota"] == 2
            assert by_id[created["id"]]["claimedCount"] == 2
        finally:
            await _cleanup([created["id"]])

    async def test_redeem_rejects_expired_promotion(self, client, boss):
        """窗口判定与结算同口径:status active 但已过 end_at → 补录核销拒绝。"""
        from engine_py.tools_registry.order_domain import _merchant_writer_engine
        from sqlalchemy import text

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        async with _merchant_writer_engine().begin() as conn:
            await conn.execute(text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, shipping_address) "
                "VALUES ('E2E-QT-ORD', 'CUST-QT-1', 'PAID', 500, '{}'::jsonb) "
                "ON CONFLICT (order_id) DO UPDATE SET status = 'PAID', total_amount = 500"
            ))

        now = datetime.now()
        created = await self._create(client, boss, "E2E 过期核销", "full_reduction", threshold=100, value=10,
                                     startAt=(now - timedelta(days=2)).isoformat(),
                                     endAt=(now - timedelta(days=1)).isoformat())
        try:
            r = await client.post(f"/api/admin/analytics/promotions/{created['id']}/redeem",
                                  headers=boss, json={"orderId": "E2E-QT-ORD"})
            assert r.status_code == 400
            assert "已结束" in r.json()["error"]
        finally:
            await _cleanup([created["id"]])
            async with _merchant_writer_engine().begin() as conn:
                await conn.execute(text("DELETE FROM merchant_order_items WHERE order_id = 'E2E-QT-ORD'"))
                await conn.execute(text("DELETE FROM merchant_orders WHERE order_id = 'E2E-QT-ORD'"))
