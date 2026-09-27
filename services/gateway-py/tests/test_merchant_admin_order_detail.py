"""商户后台订单详情契约(GET /api/admin/orders/{order_id})。

商户后台订单管理此前只有列表(裸 merchant_orders 行,无行项目)与一键发货,
没有任何详情入口 —— 本契约钉死补齐的详情端点行为:

1. 200:order 与 storefront /spi/v1/orders/detail 同形(camelCase,含 items
   行项目与 originalAmount/discountAmount 账本三行),auditLogs 只含该订单
   的审计时间线;
2. 404:查无订单诚实 404(不静默回空对象假装成功);
3. 与列表端点互不截胡:GET /api/admin/orders 列表契约不受新路由影响。
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from .conftest import _TS

pytestmark = pytest.mark.usefixtures("seeded")

_DETAIL_ORDER_ID = f"MA-DETAIL-{_TS}"


async def _seed_detail_order() -> None:
    from engine_py.tools_registry.order_domain import _merchant_writer_engine

    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()
    async with _merchant_writer_engine().begin() as c:
        await c.execute(sa.text(
            "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, discount_amount, "
            "shipping_address, tracking_info) "
            "VALUES (:oid, 'CUST-DETAIL', 'PAID', 499.00, 50.00, "
            "CAST('{\"recipientName\":\"张伟\",\"phone\":\"13800138000\",\"fullAddress\":\"浙江省杭州市\"}' AS jsonb), "
            "NULL) ON CONFLICT (order_id) DO UPDATE SET total_amount = 499.00, discount_amount = 50.00"
        ), {"oid": _DETAIL_ORDER_ID})
        await c.execute(sa.text(
            "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, quantity, price) "
            "SELECT :oid, 'SPU-DETAIL-001', 'SKU-DETAIL-001', '极光轻量三防连帽冲锋衣', '曜石黑/L', 1, 499.00 "
            "WHERE NOT EXISTS (SELECT 1 FROM merchant_order_items WHERE order_id = :oid AND sku_code = 'SKU-DETAIL-001')"
        ), {"oid": _DETAIL_ORDER_ID})
        await c.execute(sa.text(
            "INSERT INTO merchant_audit_logs (action_type, order_id, idempotency_key, operator, payload, result) "
            "VALUES ('ship', :oid, :ik, 'merchant_operator', CAST('{}' AS jsonb), CAST('{}' AS jsonb)) "
            "ON CONFLICT (idempotency_key) DO NOTHING"
        ), {"oid": _DETAIL_ORDER_ID, "ik": f"idem_{_DETAIL_ORDER_ID}"})


class TestMerchantAdminOrderDetail:
    async def test_detail_returns_storefront_shape_with_items_and_scoped_audit(self, client, staff_auth):
        """详情同形 storefront 序列化:items 行项目 + 账本三行 + 审计只含本单。"""
        await _seed_detail_order()
        r = await client.get(f"/api/admin/orders/{_DETAIL_ORDER_ID}", headers=staff_auth)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        order = body["order"]
        assert order["orderId"] == _DETAIL_ORDER_ID
        assert order["status"] == "PAID"
        assert order["totalAmount"] == 499.0
        assert order["discountAmount"] == 50.0
        assert order["originalAmount"] == 549.0
        assert order["shippingAddress"]["recipientName"] == "张伟"
        assert len(order["items"]) == 1
        item = order["items"][0]
        assert item["skuId"] == "SKU-DETAIL-001"
        assert item["title"] == "极光轻量三防连帽冲锋衣"
        assert item["quantity"] == 1
        assert item["price"] == 499.0
        logs = body["auditLogs"]
        assert len(logs) == 1
        assert logs[0]["order_id"] == _DETAIL_ORDER_ID
        assert logs[0]["action_type"] == "ship"

    async def test_missing_order_is_honest_404(self, client, staff_auth):
        r = await client.get("/api/admin/orders/MA-NOT-EXISTS-000", headers=staff_auth)
        assert r.status_code == 404
        body = r.json()
        assert body["success"] is False
        assert "不存在" in body["error"]

    async def test_orders_list_endpoint_unaffected(self, client, staff_auth):
        """列表端点契约不被新详情路由截胡/改形(A4 收口后须在职员工身份)。"""
        await _seed_detail_order()
        r = await client.get("/api/admin/orders", headers=staff_auth)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert any(o["order_id"] == _DETAIL_ORDER_ID for o in body["orders"])
