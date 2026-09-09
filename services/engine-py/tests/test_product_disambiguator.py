"""破损图商品归属消歧回归(grilling 2026-09-09 共识)。

全桩注入(LLM/订单查询零真实依赖),钉死:
- 候选池门面 get_recent_product_lines:商户真单(agent_merchant)优先、
  engine 本地表兜底、商品行拍平、近 N 单截断、空用户短路(2026-09-09
  冒烟暴露:商户用户在 engine 表无单,直查 detailed 永远空候选);
- 消歧:唯一高置信命中 → matched(注入 targetOrderId 的数据来源);
- 防幻觉:命中项必须原样存在于候选集,编造单号/低置信一律 ambiguous;
- 降级:LLM 失败/无视觉摘要/无候选 → ambiguous 或 no_orders,绝不抛出。

挂载侧(intent_triage_engine Step 1.6)不在此钉 —— process() 依赖 DB/Redis
全链路,行为由真实链路手验;本套钉 helper 的分支边界即挂载逻辑的输入面。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.tools_registry import order_domain
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


def _candidates_fixture() -> list[dict]:
    return [
        {"orderId": "ORD-1001", "productName": "Nike Air 红色运动鞋", "quantity": 1},
        {"orderId": "ORD-1001", "productName": "灰色连帽卫衣", "quantity": 2},
        {"orderId": "ORD-1002", "productName": "玻璃茶具套装", "quantity": 1},
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


def _wire_candidates(monkeypatch: pytest.MonkeyPatch, lines_by_user: dict[str, list[dict]] | list[dict]) -> None:
    """替换候选池门面:传 dict 按 user_id 分发(None 映射空,镜像门面对空用户短路)。"""

    async def fake_lines(user_id, business_id=None, limit=5):
        if isinstance(lines_by_user, dict):
            return lines_by_user.get(user_id or "", [])[:limit]
        return lines_by_user[:limit]

    monkeypatch.setattr(OrderDomainService, "get_recent_product_lines", fake_lines)


def _match(order_id: str | None, product: str | None, confidence: float) -> ProductMatch:
    return ProductMatch(order_id=order_id, product_name=product, confidence=confidence)


class TestDisambiguateProduct:
    def test_no_orders_when_user_has_none(self, monkeypatch):
        _wire_candidates(monkeypatch, [])
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=_FakeModel(_match(None, None, 0.9))))
        assert result["status"] == "no_orders"
        assert result["candidates"] == []

    def test_matched_on_unique_high_confidence(self, monkeypatch):
        _wire_candidates(monkeypatch, _candidates_fixture())
        model = _FakeModel(_match("ORD-1001", "Nike Air 红色运动鞋", 0.92))
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=model))
        assert result["status"] == "matched"
        assert result["orderId"] == "ORD-1001"
        assert result["productName"] == "Nike Air 红色运动鞋"
        assert result["confidence"] == 0.92

    def test_low_confidence_falls_back_to_ambiguous(self, monkeypatch):
        _wire_candidates(monkeypatch, _candidates_fixture())
        model = _FakeModel(_match("ORD-1002", "玻璃茶具套装", 0.55))
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=model))
        assert result["status"] == "ambiguous"
        assert len(result["candidates"]) == 3

    def test_hallucinated_order_id_rejected(self, monkeypatch):
        # 防幻觉:模型编造候选之外的订单号,即便高置信也必须降级 ambiguous
        _wire_candidates(monkeypatch, _candidates_fixture())
        model = _FakeModel(_match("ORD-FAKE-999", "Nike Air 红色运动鞋", 0.95))
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=model))
        assert result["status"] == "ambiguous"

    def test_llm_failure_degrades_to_ambiguous_with_candidates(self, monkeypatch):
        _wire_candidates(monkeypatch, _candidates_fixture())
        model = _FakeModel(RuntimeError("llm down"))
        result = asyncio.run(disambiguate_product(_VISION, "CUST-1", "aurora", model=model))
        assert result["status"] == "ambiguous"
        assert len(result["candidates"]) == 3

    def test_empty_vision_summary_skips_llm(self, monkeypatch):
        # spy 必须在 try 块外记录:LLM 调用落在 except Exception 内,
        # 仅靠"结果 ambiguous"无法区分主动短路与异常降级
        _wire_candidates(monkeypatch, _candidates_fixture())
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

    def test_missing_user_id_short_circuits(self, monkeypatch):
        # 空用户:门面契约返回空候选 → no_orders,不进 LLM
        _wire_candidates(monkeypatch, {"": []})
        result = asyncio.run(disambiguate_product(_VISION, None, "aurora", model=_FakeModel(_match(None, None, 0.9))))
        assert result["status"] == "no_orders"


class TestGetRecentProductLines:
    """候选池门面:两库优先级(商户真单优先/engine 兜底)+ 拍平 + 截断。"""

    @staticmethod
    def _wire_merchant(monkeypatch, orders: list[dict] | None, items_by_order: dict[str, list[dict]]):
        async def fake_list(_user_id):
            return orders

        async def fake_items(order_id):
            return items_by_order.get(order_id, [])

        monkeypatch.setattr(order_domain, "_list_merchant_orders", fake_list)
        monkeypatch.setattr(order_domain, "_fetch_merchant_order_items", fake_items)

    @staticmethod
    def _wire_engine_detailed(monkeypatch, orders: list[dict]):
        calls = []

        async def fake_detailed(options):
            calls.append(options)
            return orders

        monkeypatch.setattr(OrderDomainService, "get_user_orders_detailed", fake_detailed)
        return calls

    def test_merchant_orders_take_priority_over_engine(self, monkeypatch):
        # 商户真单命中时不得再碰 engine 本地表(2026-09-09 冒烟:直查 detailed 对商户用户永远空)
        self._wire_merchant(
            monkeypatch,
            [{"orderId": "AURORA-ORD-2026-9081"}, {"orderId": "AURORA-ORD-2026-9082"}],
            {
                "AURORA-ORD-2026-9081": [{"name": "极光机能夹克", "quantity": 1, "price": 1299.0}],
                "AURORA-ORD-2026-9082": [{"name": "轻量跑步鞋", "quantity": 1, "price": 589.0}],
            },
        )
        engine_calls = self._wire_engine_detailed(monkeypatch, [{"orderId": "ORD-ENGINE"}])

        lines = asyncio.run(OrderDomainService.get_recent_product_lines("CUST-8801", "aurora"))
        assert lines == [
            {"orderId": "AURORA-ORD-2026-9081", "productName": "极光机能夹克", "quantity": 1},
            {"orderId": "AURORA-ORD-2026-9082", "productName": "轻量跑步鞋", "quantity": 1},
        ]
        assert engine_calls == []

    def test_merchant_unreachable_falls_back_to_engine(self, monkeypatch):
        # 商户库不可达(None)静默降级 engine 本地表
        self._wire_merchant(monkeypatch, None, {})
        self._wire_engine_detailed(
            monkeypatch,
            [
                {
                    "orderId": "ORD-2001",
                    "items": [
                        {"productName": "Nike Air 红色运动鞋", "quantity": 1},
                        {"productName": "灰色连帽卫衣", "quantity": 2},
                    ],
                }
            ],
        )
        lines = asyncio.run(OrderDomainService.get_recent_product_lines("demo-user-uuid", "nike"))
        assert lines == [
            {"orderId": "ORD-2001", "productName": "Nike Air 红色运动鞋", "quantity": 1},
            {"orderId": "ORD-2001", "productName": "灰色连帽卫衣", "quantity": 2},
        ]

    def test_caps_orders_at_limit_before_item_fetch(self, monkeypatch):
        fetched_order_ids = []

        async def fake_list(_user_id):
            return [{"orderId": f"ORD-{n}"} for n in range(8)]

        async def fake_items(order_id):
            fetched_order_ids.append(order_id)
            return [{"name": f"商品{order_id}", "quantity": 1}]

        monkeypatch.setattr(order_domain, "_list_merchant_orders", fake_list)
        monkeypatch.setattr(order_domain, "_fetch_merchant_order_items", fake_items)

        lines = asyncio.run(OrderDomainService.get_recent_product_lines("CUST-8801", limit=5))
        assert len(lines) == MAX_CANDIDATE_ORDERS
        assert fetched_order_ids == [f"ORD-{n}" for n in range(MAX_CANDIDATE_ORDERS)]  # 超限单不白查 items

    def test_empty_user_returns_empty_without_db_touch(self, monkeypatch):
        async def boom_list(_user_id):
            raise AssertionError("空用户不应触达商户库")

        monkeypatch.setattr(order_domain, "_list_merchant_orders", boom_list)
        assert asyncio.run(OrderDomainService.get_recent_product_lines(None, "aurora")) == []


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
