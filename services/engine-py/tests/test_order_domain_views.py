"""回归:聊天查单视图必须与商户门户"我的订单"列表同源(2026-09-05)。

背景 bug:商户 App 里聊天问"查询我的订单"与订单列表页展示完全不同——
1. 聊天 listUserOrders 只读 engine 本地 orders 表,而商城下单只写
   agent_merchant.merchant_orders,两视图物理隔离;
2. engine 空结果时自动自愈注入 2 笔虚构演示订单(¥199/¥89);
3. 两侧查询均 OR user_id='CUST-8801',任何用户都会混入张伟的订单。

修复后契约:list_user_orders 商户真单优先、严格归属、绝不播种;
engine 本地表兜底 SQL 不得包含 OR CUST-8801。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.tools_registry import order_domain
from engine_py.tools_registry.order_domain import OrderDomainService

_MERCHANT_ROWS = [
    {
        "orderId": "AURORA-ORD-2026-9081",
        "status": "PAID",
        "userId": "CUST-8802",
        "businessId": "aurora",
        "totalAmount": 1299.0,
        "currency": "CNY",
        "source": "merchant",
    },
    {
        "orderId": "AURORA-ORD-2026-9082",
        "status": "SHIPPED",
        "userId": "CUST-8802",
        "businessId": "aurora",
        "totalAmount": 589.0,
        "currency": "CNY",
        "source": "merchant",
    },
]


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """记录执行过的 SQL,返回预置行;不触达任何真实数据库。"""

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


def _forbid_seeding(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list[dict] = []

    async def fail_if_called(options: dict) -> dict:
        calls.append(options)
        return {"orderId": options.get("orderId")}

    monkeypatch.setattr(OrderDomainService, "create_order", staticmethod(fail_if_called))
    return calls


def test_list_prefers_merchant_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """商户真单存在时,聊天列表必须原样返回商户视图(与列表页同源)。"""

    async def fake_merchant(uid: str):
        return list(_MERCHANT_ROWS) if uid == "CUST-8802" else []

    def fail_session():
        raise AssertionError("商户真单命中后不得再查 engine 本地表")

    monkeypatch.setattr(order_domain, "_list_merchant_orders", fake_merchant)
    monkeypatch.setattr(order_domain, "get_session", fail_session)
    seeding = _forbid_seeding(monkeypatch)

    result = asyncio.run(OrderDomainService.list_user_orders(user_id="CUST-8802", business_id="aurora"))

    assert [o["orderId"] for o in result["orders"]] == ["AURORA-ORD-2026-9081", "AURORA-ORD-2026-9082"]
    assert seeding == []


def test_list_empty_never_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """两侧皆空时诚实返回空列表,绝不自愈注入虚构演示订单。"""

    async def fake_merchant(uid: str):
        return []

    monkeypatch.setattr(order_domain, "_list_merchant_orders", fake_merchant)
    monkeypatch.setattr(order_domain, "get_session", lambda: _FakeSession([]))
    seeding = _forbid_seeding(monkeypatch)

    result = asyncio.run(OrderDomainService.list_user_orders(user_id="CUST-8803", business_id="aurora"))

    assert result["orders"] == []
    assert seeding == []


def test_engine_fallback_sql_strict_scoping(monkeypatch: pytest.MonkeyPatch) -> None:
    """engine 本地表兜底 SQL 必须严格 user_id 归属,不得 OR CUST-8801 混入他人订单。"""

    async def fake_merchant(uid: str):
        return None  # 商户库不可达 → 降级本地表

    session = _FakeSession([])
    monkeypatch.setattr(order_domain, "_list_merchant_orders", fake_merchant)
    monkeypatch.setattr(order_domain, "get_session", lambda: session)
    _forbid_seeding(monkeypatch)

    result = asyncio.run(OrderDomainService.list_user_orders(user_id="CUST-8803", business_id="nike"))

    assert result["orders"] == []
    assert len(session.executed_sql) == 1
    sql = session.executed_sql[0]
    assert '"user_id" = :uid' in sql
    assert "CUST-8801" not in sql, "兜底 SQL 不得包含 OR CUST-8801 跨用户回退"


def test_find_order_by_id_uses_merchant_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """按单号查询:engine 本地未命中时须经商户库回退解析(严格归属)。"""

    async def fake_merchant_find(order_id: str, uid: str):
        return _MERCHANT_ROWS[0] if uid == "CUST-8802" and order_id == "AURORA-ORD-2026-9081" else None

    monkeypatch.setattr(order_domain, "_find_merchant_order", fake_merchant_find)

    session = _FakeSession([])  # engine orders / third_party 均未命中
    monkeypatch.setattr(order_domain, "get_session", lambda: session)

    order = asyncio.run(OrderDomainService.find_order_by_id("AURORA-ORD-2026-9081", "CUST-8802", "aurora"))
    assert order is not None and order["orderId"] == "AURORA-ORD-2026-9081"
    assert order["source"] == "merchant"

    # 他人订单不得经商户库回返回给当前用户
    leaked = asyncio.run(OrderDomainService.find_order_by_id("AURORA-ORD-2026-9081", "CUST-8803", "aurora"))
    assert leaked is None
