"""订单链租户契约(2026-10-13/14 夜评 🟡 批次收口):merchant_orders 此前零
business_id 列 —— admin 三路由(列表/详情/发货)与 storefront 详情零属主过滤,
A 店员工可读/发 B 店订单,凭 orderId 可读任意订单(IDOR)。

收口面:
1. merchant_orders 补租户列(S5 幂等迁移同款)+ 下单单点写列;
2. admin 列表/详情/发货按 scope.tenant 属主闸(闸不中诚实 404,不泄存在性);
3. store 详情收 customerId 属主闸(缺失 400,不匹配 404)。
"""

from __future__ import annotations

import uuid as _uuid

import pytest
import sqlalchemy as sa

from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine
from tests.merchant_seed_helpers import seed_merchant_catalog, seed_merchant_order

_TAG = "OTN"
_UID = "CUST-OTN-1"
_SPUCODE = "OTN-SPU-1"
_SKUCODE = "OTN-SKU-1"


async def _seed_catalog() -> None:
    await ensure_merchant_tables()
    async with merchant_engine().begin() as conn:
        await seed_merchant_catalog(
            conn,
            spu_code=_SPUCODE,
            sku_code=_SKUCODE,
            price=100.0,
            stock=99,
            title="订单租户测试商品",
            spec='{"颜色":"黑"}',
        )


async def _seed_order(order_id: str, business_id: str, customer_id: str = _UID) -> None:
    await ensure_merchant_tables()
    async with merchant_engine().begin() as conn:
        await seed_merchant_order(
            conn,
            order_id=order_id,
            customer_id=customer_id,
            total_amount=100.0,
            business_id=business_id,
            on_conflict_update=True,
        )


async def _cleanup() -> None:
    async with merchant_engine().begin() as conn:
        await conn.execute(
            sa.text(
                "DELETE FROM merchant_order_items WHERE order_id LIKE :p OR order_id IN "
                "(SELECT order_id FROM merchant_orders WHERE customer_id = :u)"
            ),
            {"p": f"{_TAG}-%", "u": _UID},
        )
        await conn.execute(
            sa.text("DELETE FROM merchant_audit_logs WHERE order_id LIKE :p"), {"p": f"{_TAG}-%"}
        )
        await conn.execute(
            sa.text(
                "DELETE FROM merchant_orders WHERE order_id LIKE :p OR customer_id = :u"
            ),
            {"p": f"{_TAG}%", "u": _UID},
        )
        await conn.execute(sa.text("DELETE FROM merchant_skus WHERE sku_code = :c"), {"c": _SKUCODE})
        await conn.execute(sa.text("DELETE FROM merchant_spus WHERE spu_code = :c"), {"c": _SPUCODE})


@pytest.fixture(autouse=True)
async def _order_chain_env():
    await _seed_catalog()
    yield
    await _cleanup()


def _order_id(tag: str) -> str:
    return f"{_TAG}-{tag}-{str(_uuid.uuid4())[:8].upper()}"


class TestOrderTenantColumn:
    async def test_place_order_writes_business_id(self, client, contract_fixtures):
        """下单写租户列:显式 businessId 落行值,缺省 aurora(单店部署口径)。"""
        res = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "skuCode": _SKUCODE, "quantity": 1, "businessId": "nike"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["success"] is True, body
        async with merchant_engine().connect() as conn:
            biz = (
                await conn.execute(
                    sa.text("SELECT business_id FROM merchant_orders WHERE order_id = :o"),
                    {"o": body["orderId"]},
                )
            ).scalar()
        assert biz == "nike", f"显式租户必须落列: {biz}"

        res2 = await client.post(
            "/api/store/orders",
            json={"customerId": _UID, "skuCode": _SKUCODE, "quantity": 1},
        )
        assert res2.status_code == 200, res2.text
        body2 = res2.json()
        assert body2["success"] is True, body2
        async with merchant_engine().connect() as conn:
            biz2 = (
                await conn.execute(
                    sa.text("SELECT business_id FROM merchant_orders WHERE order_id = :o"),
                    {"o": body2["orderId"]},
                )
            ).scalar()
        assert biz2 == "aurora", f"缺省须落单店口径 aurora: {biz2}"


class TestAdminOrderTenantGate:
    async def test_detail_cross_tenant_honest_404(self, client, staff_auth):
        """A 店员工读 B 店订单:闸不中诚实 404,不泄存在性。"""
        order_id = _order_id("NIKE")
        await _seed_order(order_id, "nike")
        r = await client.get(f"/api/admin/orders/{order_id}", headers=staff_auth)
        assert r.status_code == 404, f"跨租户详情必须 404: {r.status_code} {r.text}"

        own_id = _order_id("AURORA")
        await _seed_order(own_id, "aurora")
        r_own = await client.get(f"/api/admin/orders/{own_id}", headers=staff_auth)
        assert r_own.status_code == 200, r_own.text
        assert r_own.json()["order"]["orderId"] == own_id

    async def test_ship_cross_tenant_rejected(self, client, staff_auth):
        """A 店员工发 B 店订单:拒绝且订单状态纹丝不动(资金/履约面闸)。"""
        order_id = _order_id("NIKE")
        await _seed_order(order_id, "nike")
        r = await client.post(
            "/api/admin/orders/ship",
            json={"orderId": order_id, "trackingNo": "SF-OTN-CROSS"},
            headers=staff_auth,
        )
        assert r.status_code == 404, f"跨租户发货必须拒绝: {r.status_code} {r.text}"
        async with merchant_engine().connect() as conn:
            status = (
                await conn.execute(
                    sa.text("SELECT status FROM merchant_orders WHERE order_id = :o"), {"o": order_id}
                )
            ).scalar()
        assert status == "PAID", f"跨租户发货不得落任何副作用: {status}"

    async def test_dashboard_orders_scoped_by_tenant(self, client, staff_auth):
        """运营台列表只见本店订单:B 店订单不得出现在 A 店员工视图。"""
        nike_id = _order_id("NIKE")
        aurora_id = _order_id("AURORA")
        await _seed_order(nike_id, "nike")
        await _seed_order(aurora_id, "aurora")
        body = (await client.get("/api/admin/orders", headers=staff_auth)).json()
        ids = {o["order_id"] for o in body["orders"]}
        assert aurora_id in ids, f"本店订单必须在列表: {aurora_id}"
        assert nike_id not in ids, "跨租户订单严禁进运营台列表"


class TestStoreOrderDetailOwnership:
    async def test_idor_gate(self, client):
        """凭 orderId 裸读任意订单(IDOR)封死:customerId 缺失 400,
        他人 404 不泄存在性,属主 200。"""
        order_id = _order_id("MINE")
        await _seed_order(order_id, "aurora", customer_id=_UID)

        missing = await client.get(f"/api/store/orders/{order_id}")
        assert missing.status_code == 400, f"缺 customerId 必须诚实 400: {missing.status_code}"

        foreign = await client.get(f"/api/store/orders/{order_id}", params={"customerId": "CUST-OTN-OTHER"})
        assert foreign.status_code == 404, f"他人读取必须 404: {foreign.status_code}"

        mine = await client.get(f"/api/store/orders/{order_id}", params={"customerId": _UID})
        assert mine.status_code == 200, mine.text
        assert mine.json()["order"]["orderId"] == order_id
