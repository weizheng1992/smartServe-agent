"""场景化快捷回复(ADR-0001,2026-09-12):按本轮意图出组,死按钮禁令。

旧世界:每轮纯文本回复固定追加同一组「物流/退款/照片/人工」四件套,不看
场景;域卡片轮整行不出现(run_agent short-circuit)。产品要求:退款场景给
「查询最近的订单 / 查询未发货的订单」,商品场景给品类快捷入口。

契约(用户逐项裁决「按照推荐」):
- Q1 场景判定按本轮已分类意图映射;
- Q2 退款场景组 = 查询最近的订单/查询未发货的订单/上传照片/人工,场景内
  撤下「申请退款服务」(用户已在退款流程里);
- Q3 品类 chips 只能来自真货架盘点数据(shelfCategories),文案严禁
  「热销/卖得好/爆款」(2.6.8 铁律延伸到 UI 层);盘点空 → 退通用组,
  严禁编造品类;
- Q4 short-circuit 改追加:域卡片轮也挂场景组;排行卡指标消歧组优先级
  不受扰(2.6.12 契约);
- Q5 兜底通用组 = 查询我的订单/逛逛商城/申请退款/人工(旧「查询物流进度」
  并入订单查询——同一意图同一出口)。
"""

from __future__ import annotations

import asyncio

from engine_py.cards.card_synthesizer import CardSynthesizer
from engine_py.tools_registry.mall_domain import MallDomainService


def _quick_replies_data(cards: list[dict]) -> dict | None:
    qr = [c for c in cards if c.get("type") == "quick_replies"]
    return qr[-1]["data"] if qr else None


def _labels(data: dict | None) -> list[str]:
    return [o.get("label", "") for o in (data or {}).get("options", [])]


# ── Q2: 退款场景组 ────────────────────────────────────────────────────────


def test_refund_intent_gets_refund_scene() -> None:
    data = _quick_replies_data(CardSynthesizer.synthesize_cards({"intents": [{"intent": "refund"}]}))
    labels = _labels(data)
    assert any("查询最近的订单" in lb for lb in labels)
    assert any("查询未发货的订单" in lb for lb in labels)
    assert any("上传商品瑕疵照片" in lb for lb in labels)
    assert any("人工" in lb for lb in labels)
    joined = " ".join(labels)
    assert "申请退款" not in joined, "用户已在退款流程中,场景内不得再挂「申请退款」按钮"


def test_order_return_intent_maps_to_refund_scene() -> None:
    data = _quick_replies_data(CardSynthesizer.synthesize_cards({"intents": [{"intent": "order_return"}]}))
    labels = _labels(data)
    assert any("查询最近的订单" in lb for lb in labels)
    assert any("查询未发货的订单" in lb for lb in labels)


def test_refund_scene_upload_action_opens_file_picker() -> None:
    """照片按钮是真实能力(trigger_upload → /api/chat/upload → 视觉定责)。"""
    data = _quick_replies_data(CardSynthesizer.synthesize_cards({"intents": [{"intent": "refund"}]}))
    upload = next(o for o in data["options"] if "上传" in o["label"])
    assert upload["action"] == "trigger_upload"


# ── Q5: 兜底通用组 ────────────────────────────────────────────────────────


def test_default_scene_generic_set() -> None:
    data = _quick_replies_data(CardSynthesizer.synthesize_cards({"intents": [{"intent": "consult"}]}))
    labels = _labels(data)
    assert any("查询我的订单" in lb for lb in labels)
    assert any("逛逛商城" in lb for lb in labels)
    assert any("申请退款" in lb for lb in labels)
    assert any("人工" in lb for lb in labels)
    joined = " ".join(labels)
    assert "未发货" not in joined, "未发货过滤属售后场景专属,通用组不挂"


def test_missing_intents_still_gets_generic_set() -> None:
    """intents 缺省(如 planner 路径)不炸、照常兜底。"""
    data = _quick_replies_data(CardSynthesizer.synthesize_cards({}))
    assert any("查询我的订单" in lb for lb in _labels(data))


# ── Q3: 品类 chips 只来自真货架,严禁「热销」话术 ─────────────────────────


_GUIDE_CATEGORIES = [
    {"category": "潮流鞋靴", "spuCount": 2},
    {"category": "背包收纳", "spuCount": 3},
]


def test_guide_scene_chips_from_real_shelf_only() -> None:
    data = _quick_replies_data(
        CardSynthesizer.synthesize_cards(
            {"intents": [{"intent": "shopping_guide"}], "shelfCategories": _GUIDE_CATEGORIES}
        )
    )
    labels = _labels(data)
    assert any("潮流鞋靴" in lb and "2" in lb for lb in labels), "chips 必须带真实在售款数"
    assert any("背包收纳" in lb and "3" in lb for lb in labels)
    shoe = next(o for o in data["options"] if "潮流鞋靴" in o["label"])
    assert shoe["action"] == "send_message"
    assert "潮流鞋靴" in shoe["payload"]["text"], "点击文本必须带品类名走导购浏览"
    # 数据驱动:输入里没有的品类绝不出现
    assert not any("露营装备" in lb for lb in labels)


def test_guide_chips_forbid_hot_selling_wording() -> None:
    """商户货架无销量列(2.6.8 铁律):文案严禁「热销/卖得好/爆款」。"""
    data = _quick_replies_data(
        CardSynthesizer.synthesize_cards(
            {"intents": [{"intent": "shopping_guide"}], "shelfCategories": _GUIDE_CATEGORIES}
        )
    )
    joined = data["title"] + " ".join(_labels(data))
    assert "热销" not in joined
    assert "卖得好" not in joined and "卖的好" not in joined
    assert "爆款" not in joined


def test_guide_scene_without_shelf_data_falls_back_to_default() -> None:
    """盘点空(库不可达/诚实空)→ 退通用组,严禁编造品类 chips。"""
    data = _quick_replies_data(
        CardSynthesizer.synthesize_cards({"intents": [{"intent": "shopping_guide"}], "shelfCategories": []})
    )
    labels = _labels(data)
    assert any("查询我的订单" in lb for lb in labels)
    assert not any("款" in lb and "鞋靴" in lb for lb in labels)


# ── Q4: 追加语义与排行卡优先级 ────────────────────────────────────────────


def test_existing_cards_keep_position_scene_replies_appended() -> None:
    """域卡片轮:域卡保位,场景组追加在尾部(short-circuit 拆除)。"""
    domain_card = {"type": "order_card", "data": {"orderId": "AURORA-ORD-1", "status": "PAID"}}
    cards = CardSynthesizer.synthesize_cards(
        {"intents": [{"intent": "refund"}], "existingCards": [domain_card]}
    )
    assert cards[0] == domain_card, "域卡片必须原样保位"
    assert cards[-1]["type"] == "quick_replies"
    assert any("查询最近的订单" in lb for lb in _labels(_quick_replies_data(cards)))


def test_skill_authored_quick_replies_win_no_double_row() -> None:
    """技能自带的 quick_replies(如破损照片消歧组)是更具体的场景行:
    保留它、不再追加场景组 —— 严禁一屏出现两条快捷回复胶囊。"""
    skill_row = {
        "type": "quick_replies",
        "data": {"title": "请问破损的是哪件商品？", "options": [{"label": "订单 A 的背包", "action": "send_message", "payload": {"text": "我反馈的是订单 A"}}]},
    }
    cards = CardSynthesizer.synthesize_cards(
        {"intents": [{"intent": "refund"}], "existingCards": [skill_row]}
    )
    qr_cards = [c for c in cards if c.get("type") == "quick_replies"]
    assert len(qr_cards) == 1, "严禁双胶囊"
    assert qr_cards[0] is skill_row, "技能自带的场景行必须原样保留"


def test_ranking_card_disambiguation_beats_scene_map() -> None:
    """2.6.12 契约不受扰:排行卡轮挂指标消歧组,不挂品类 chips。"""
    ranking_output = {
        "success": True,
        "rankingMetric": "gmv",
        "metricLabel": "总销售额 (GMV)",
        "itemCount": 1,
        "products": [{"rank": 1, "productId": "p1", "name": "x", "totalGmv": 100.0, "metricDisplay": "100 元"}],
    }
    task_plan = {
        "subtasks": [
            {"id": "rank_products_1", "description": "查询商品排行", "status": "completed",
             "result": {"toolExecuted": "queryProductRanking", "output": ranking_output}}
        ]
    }
    data = _quick_replies_data(
        CardSynthesizer.synthesize_cards(
            {
                "taskPlan": task_plan,
                "intents": [{"intent": "shopping_guide"}],
                "shelfCategories": _GUIDE_CATEGORIES,
            }
        )
    )
    assert "统计口径" in data["title"]
    assert not any("潮流鞋靴" in lb for lb in _labels(data))


# ── fetch_shelf_categories:购物轮实查,失败诚实空 ─────────────────────────


def test_fetch_shelf_categories_zero_query_off_guide(monkeypatch) -> None:
    calls: list[int] = []

    async def fake_overview() -> list[dict]:
        calls.append(1)
        return [{"category": "潮流鞋靴", "spuCount": 2}]

    monkeypatch.setattr(MallDomainService, "get_shelf_overview", staticmethod(fake_overview))
    out = asyncio.run(CardSynthesizer.fetch_shelf_categories([{"intent": "refund"}]))
    assert out == []
    assert calls == [], "非购物轮零查库"


def test_fetch_shelf_categories_pulls_overview_on_guide_turn(monkeypatch) -> None:
    async def fake_overview() -> list[dict]:
        return [{"category": "潮流鞋靴", "spuCount": 2}, {"category": "露营装备", "spuCount": 2}]

    monkeypatch.setattr(MallDomainService, "get_shelf_overview", staticmethod(fake_overview))
    out = asyncio.run(CardSynthesizer.fetch_shelf_categories([{"intent": "shopping_guide"}]))
    assert [c["category"] for c in out] == ["潮流鞋靴", "露营装备"]


def test_fetch_shelf_categories_degrades_honest_empty(monkeypatch) -> None:
    async def boom() -> list[dict]:
        raise RuntimeError("merchant db down")

    monkeypatch.setattr(MallDomainService, "get_shelf_overview", staticmethod(boom))
    out = asyncio.run(CardSynthesizer.fetch_shelf_categories([{"intent": "shopping_guide"}]))
    assert out == [], "盘点不可达必须诚实空,该轮不挂品类 chips"
