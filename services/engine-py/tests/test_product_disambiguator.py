"""破损图商品归属消歧回归(grilling 2026-09-09 共识)。

全桩注入(LLM/订单查询零真实依赖),钉死四类分支:
- 候选池:多单商品行拍平、近 5 单截断、空用户短路;
- 消歧:唯一高置信命中 → matched(注入 targetOrderId 的数据来源);
- 防幻觉:命中项必须原样存在于候选集,编造单号/低置信一律 ambiguous;
- 降级:LLM 失败/无视觉摘要/无候选 → ambiguous 或 no_orders,绝不抛出。

挂载侧(intent_triage_engine Step 1.6)不在此钉 —— process() 依赖 DB/Redis
全链路,行为由真实链路手验;本套钉 helper 的分支边界即挂载逻辑的输入面。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.tools_registry.order_domain import OrderDomainService
from engine_py.triage.product_disambiguator import (
    MAX_CANDIDATE_ORDERS,
    MAX_CARD_OPTIONS,
    ProductMatch,
    build_select_card,
    disambiguate_product,
)

_VISION = {
    "visualSummary": "一只红色运动鞋,鞋头有明显破损",
    "detectedObjects": ["red sneaker", "shoe"],
    "extractedOrderId": None,
    "extractedTrackingNumber": None,
    "ocrText": "",
    "damageAssessment": {"damageLevel": "minor"},
}


def _orders_fixture() -> list[dict]:
    return [
        {
            "orderId": "ORD-1001",
            "items": [
                {"productName": "Nike Air 红色运动鞋", "quantity": 1, "price": 899.0},
                {"productName": "灰色连帽卫衣", "quantity": 2, "price": 299.0},
            ],
        },
        {"orderId": "ORD-1002", "items": [{"productName": "玻璃茶具套装", "quantity": 1, "price": 159.0}]},
    ]


class _FakeStructured:
    def __init__(self, result: ProductMatch | Exception):
        self._result = result

    async def ainvoke(self, _messages):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeModel:
    def __init__(self, result: ProductMatch | Exception):
        self._result = result

    def with_structured_output(self, _schema, method=None):
        assert method == "function_calling"
        return _FakeStructured(self._result)


def _wire_orders(monkeypatch: pytest.MonkeyPatch, orders: list[dict]) -> None:
    async def fake_detailed(_options: dict) -> list[dict]:
        return orders

    monkeypatch.setattr(OrderDomainService, "get_user_orders_detailed", fake_detailed)


def _match(order_id: str | None, product: str | None, confidence: float) -> ProductMatch:
    return ProductMatch(order_id=order_id, product_name=product, confidence=confidence)


class TestDisambiguateProduct:
    def test_no_orders_when_user_has_none(self, monkeypatch):
        _wire_orders(monkeypatch, [])
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=_FakeModel(_match(None, None, 0.9))))
        assert result["status"] == "no_orders"
        assert result["candidates"] == []

    def test_matched_on_unique_high_confidence(self, monkeypatch):
        _wire_orders(monkeypatch, _orders_fixture())
        model = _FakeModel(_match("ORD-1001", "Nike Air 红色运动鞋", 0.92))
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=model))
        assert result["status"] == "matched"
        assert result["orderId"] == "ORD-1001"
        assert result["productName"] == "Nike Air 红色运动鞋"
        assert result["confidence"] == 0.92

    def test_low_confidence_falls_back_to_ambiguous(self, monkeypatch):
        _wire_orders(monkeypatch, _orders_fixture())
        model = _FakeModel(_match("ORD-1002", "玻璃茶具套装", 0.55))
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=model))
        assert result["status"] == "ambiguous"
        assert len(result["candidates"]) == 3  # 两单共 3 件商品拍平

    def test_hallucinated_order_id_rejected(self, monkeypatch):
        # 防幻觉:模型编造候选之外的订单号,即便高置信也必须降级 ambiguous
        _wire_orders(monkeypatch, _orders_fixture())
        model = _FakeModel(_match("ORD-FAKE-999", "Nike Air 红色运动鞋", 0.95))
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=model))
        assert result["status"] == "ambiguous"

    def test_llm_failure_degrades_to_ambiguous_with_candidates(self, monkeypatch):
        _wire_orders(monkeypatch, _orders_fixture())
        model = _FakeModel(RuntimeError("llm down"))
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=model))
        assert result["status"] == "ambiguous"
        assert len(result["candidates"]) == 3

    def test_empty_vision_summary_skips_llm(self, monkeypatch):
        # spy 必须在 try 块外记录:LLM 调用落在 except Exception 内,
        # 仅靠"结果 ambiguous"无法区分主动短路与异常降级
        _wire_orders(monkeypatch, _orders_fixture())
        calls = []

        class _Spy:
            def with_structured_output(self, *_a, **_k):
                calls.append(1)
                return _FakeStructured(_match(None, None, 0.9))

        result = asyncio.run(
            disambiguate_product({"visualSummary": "", "detectedObjects": []}, "CUST-1", "aurora", model=_Spy())
        )
        assert result["status"] == "ambiguous"
        assert calls == []  # LLM 未被触碰,结果来自短路分支

    def test_candidate_pool_flattens_and_caps_recent_orders(self, monkeypatch):
        orders = [
            {"orderId": f"ORD-{n}", "items": [{"productName": f"商品{n}", "quantity": 1}]} for n in range(8)
        ]
        _wire_orders(monkeypatch, orders)
        model = _FakeModel(RuntimeError("stop before llm"))
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=model))
        # 8 单只取前 MAX_CANDIDATE_ORDERS 单做候选
        assert result["status"] == "ambiguous"
        assert len(result["candidates"]) == MAX_CANDIDATE_ORDERS

    def test_missing_user_id_short_circuits(self, monkeypatch):
        _wire_orders(monkeypatch, _orders_fixture())
        result = asyncio.run(disambiguate_product(_VISION, None, "aurora", model=_FakeModel(_match(None, None, 0.9))))
        assert result["status"] == "no_orders"


class TestBuildSelectCard:
    def test_card_shape_and_send_message_payload(self):
        card = build_select_card(
            [
                {"orderId": "ORD-1001", "productName": "Nike Air 红色运动鞋", "quantity": 1},
                {"orderId": "ORD-1002", "productName": "玻璃茶具套装", "quantity": 1},
            ]
        )
        assert card["type"] == "quick_replies"
        options = card["data"]["options"]
        assert len(options) == 2
        assert options[0]["action"] == "send_message"
        # 点选文本携带订单号 → 下一轮经 ORDER_ID_RE 正则通道注入 targetOrderId
        assert "ORD-1001" in options[0]["payload"]["text"]
        assert "Nike Air 红色运动鞋" in options[0]["payload"]["text"]

    def test_card_options_capped(self):
        candidates = [{"orderId": f"ORD-{n}", "productName": f"商品{n}", "quantity": 1} for n in range(20)]
        card = build_select_card(candidates)
        assert len(card["data"]["options"]) == MAX_CARD_OPTIONS
