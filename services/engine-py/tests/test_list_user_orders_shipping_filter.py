"""回归:查单发货状态过滤(ADR-0001 Q2)——「查询未发货的订单」能力补齐。

此前 listUserOrders 零参数,「未发货」在全仓无任何过滤能力;快捷按钮
「🚚 查询未发货的订单」背后必须有真实能力兜底(死按钮禁令)。

契约:
- shipping_status ∈ UNSHIPPED / SHIPPED / DELIVERED,存储值大小写不敏感;
- UNSHIPPED = 尚未发货(status 非 shipped/delivered,含 PAID 等待发货);
- 两路(商户真单 / engine 本地表)走同一纯函数过滤,严禁语义漂移
  (2.6.8「两路永不漂移」先例);
- 未知过滤值诚实报错,严禁静默全量;
- 不传过滤 = 原行为零破坏(旧调用方回归)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.tools_registry import order_domain
from engine_py.tools_registry.order_domain import OrderDomainService

_MERCHANT_ROWS = [
    {"orderId": "AURORA-ORD-PAID", "status": "PAID", "totalAmount": 1299.0},
    {"orderId": "AURORA-ORD-SHIPPED", "status": "SHIPPED", "totalAmount": 589.0},
    {"orderId": "AURORA-ORD-DELIVERED", "status": "DELIVERED", "totalAmount": 259.0},
]


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.executed_sql: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.executed_sql.append(str(stmt))
        return _FakeResult(self.rows)


def _stub_merchant(monkeypatch: pytest.MonkeyPatch, rows: list[dict] | None) -> None:
    async def fake_merchant(uid: str):
        return list(rows) if rows is not None else None

    monkeypatch.setattr(order_domain, "_list_merchant_orders", fake_merchant)


# ── 商户真单路径 ──────────────────────────────────────────────────────────


def test_unshipped_filter_on_merchant_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_merchant(monkeypatch, _MERCHANT_ROWS)
    monkeypatch.setattr(order_domain, "get_session", lambda: (_ for _ in ()).throw(AssertionError("商户真单命中后不得再查本地表")))

    result = asyncio.run(
        OrderDomainService.list_user_orders(user_id="CUST-8802", business_id="aurora", shipping_status="UNSHIPPED")
    )

    assert [o["orderId"] for o in result["orders"]] == ["AURORA-ORD-PAID"], "未发货 = 非 shipped/delivered,PAID 必须命中"


def test_shipped_filter_on_merchant_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_merchant(monkeypatch, _MERCHANT_ROWS)
    monkeypatch.setattr(order_domain, "get_session", lambda: (_ for _ in ()).throw(AssertionError("unused")))

    result = asyncio.run(
        OrderDomainService.list_user_orders(user_id="CUST-8802", business_id="aurora", shipping_status="SHIPPED")
    )

    assert [o["orderId"] for o in result["orders"]] == ["AURORA-ORD-SHIPPED"]


def test_delivered_filter_on_merchant_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_merchant(monkeypatch, _MERCHANT_ROWS)
    monkeypatch.setattr(order_domain, "get_session", lambda: (_ for _ in ()).throw(AssertionError("unused")))

    result = asyncio.run(
        OrderDomainService.list_user_orders(user_id="CUST-8802", business_id="aurora", shipping_status="DELIVERED")
    )

    assert [o["orderId"] for o in result["orders"]] == ["AURORA-ORD-DELIVERED"]


# ── engine 本地表兜底路径:同一纯函数,同一语义 ──────────────────────────


def test_local_fallback_path_same_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_merchant(monkeypatch, None)  # 商户库不可达 → 降级本地表
    local_rows = [
        {"orderId": "LOCAL-PENDING", "status": "pending"},
        {"orderId": "LOCAL-SHIPPED", "status": "shipped"},
        {"orderId": "LOCAL-DELIVERED", "status": "delivered"},
    ]
    session = _FakeSession(local_rows)
    monkeypatch.setattr(order_domain, "get_session", lambda: session)

    result = asyncio.run(
        OrderDomainService.list_user_orders(user_id="CUST-8803", business_id="nike", shipping_status="UNSHIPPED")
    )

    assert [o["orderId"] for o in result["orders"]] == ["LOCAL-PENDING"], "存储值小写也须命中(大小写不敏感)"


def test_unshipped_semantics_case_insensitive_in_helper() -> None:
    """UNSHIPPED = 仍在等待出货:排除 shipped/delivered/refunded/cancelled。

    退款/取消单永不出货,算「未发货」会误导用户以为还有包裹在路上
    (2026-09-12 实弹修正:CUST-8801 两笔 REFUNDED 单曾被算成未发货)。"""
    rows = [
        {"orderId": "A", "status": "Paid"},
        {"orderId": "B", "status": "Shipped"},
        {"orderId": "C", "status": "REFUNDED"},
        {"orderId": "D", "status": "processing"},
        {"orderId": "E", "status": "CANCELLED"},
    ]
    filtered = order_domain._apply_shipping_filter(rows, "UNSHIPPED")
    assert [r["orderId"] for r in filtered] == ["A", "D"], "PAID/PROCESSING 算未发货;退款/取消单不算,大小写不敏感"


# ── 诚实边界 ──────────────────────────────────────────────────────────────


def test_invalid_filter_value_errors_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_merchant(monkeypatch, _MERCHANT_ROWS)
    monkeypatch.setattr(order_domain, "get_session", lambda: (_ for _ in ()).throw(AssertionError("unused")))

    result = asyncio.run(
        OrderDomainService.list_user_orders(user_id="CUST-8802", business_id="aurora", shipping_status="MAYBE")
    )

    assert "error" in result, "未知过滤值必须诚实报错"
    assert "orders" not in result, "严禁静默降级为全量列表"


def test_no_filter_keeps_legacy_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    """不传 shipping_status = 旧行为零破坏(全部返回)。"""
    _stub_merchant(monkeypatch, _MERCHANT_ROWS)
    monkeypatch.setattr(order_domain, "get_session", lambda: (_ for _ in ()).throw(AssertionError("unused")))

    result = asyncio.run(OrderDomainService.list_user_orders(user_id="CUST-8802", business_id="aurora"))

    assert [o["orderId"] for o in result["orders"]] == [
        "AURORA-ORD-PAID",
        "AURORA-ORD-SHIPPED",
        "AURORA-ORD-DELIVERED",
    ]
