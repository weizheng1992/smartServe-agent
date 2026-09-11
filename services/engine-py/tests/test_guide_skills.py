"""导购技能回归:偏好提取/超模糊追问/预算过滤/空结果/候选契约,
以及 导购 ➔ 购物车 跨技能候选传递闭环。

search_products 以桩注入保证确定性(skill 层编排契约);
MallDomainService 检索语义另由 mall 相关测试钉。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.skills.cart_manage_skill import CartManageSkill
from engine_py.skills.guide_skills import ProductInquirySkill, ShoppingGuideSkill
from engine_py.tools_registry.mall_domain import MallDomainService

_MOCK_PRODUCTS = [
    {"id": "prod_nike_air_pegasus_41", "name": "Nike Air Zoom Pegasus 41 极速轻量透气跑鞋", "price": 899.0, "stock": 58, "description": "轻量透气", "specs": {"场景": "日常慢跑"}, "category": "running_shoes"},
    {"id": "prod_nike_invincible_3", "name": "Nike ZoomX Invincible Run 3 旗舰缓震跑鞋", "price": 1299.0, "stock": 22, "description": "旗舰缓震", "specs": {"场景": "长距离"}, "category": "running_shoes"},
    {"id": "prod_nike_windrunner_jacket", "name": "Nike Windrunner 连帽运动风行者夹克外套", "price": 599.0, "stock": 45, "description": "防风外套", "specs": {"面料": "防风层"}, "category": "apparel"},
]


def _stub_search(monkeypatch: pytest.MonkeyPatch, products: list[dict]) -> list[dict]:
    """桩掉 search_products,记录调用参数。"""
    calls: list[dict] = []

    async def fake_search(params: dict) -> dict:
        calls.append(params)
        return {"total": len(products), "products": products}

    monkeypatch.setattr(MallDomainService, "search_products", staticmethod(fake_search))
    return calls


def _stub_overview(monkeypatch: pytest.MonkeyPatch, overview: list[dict]) -> None:
    """桩掉 get_shelf_overview(品类盘点,2026-09-12):空分支会调它,不桩即打真实
    商户 reader(宿主 dev DB),破坏密封。"""
    async def fake_overview() -> list[dict]:
        return overview

    monkeypatch.setattr(MallDomainService, "get_shelf_overview", staticmethod(fake_overview))


def _run_guide(text: str, guide_ctx: dict | None = None) -> dict:
    ctx = {
        "threadId": "t_guide",
        "tenantId": "ecommerce",
        "userId": "u_guide",
        "input": text,
        "slots": {},
        "extra": {"guideContext": guide_ctx} if guide_ctx else {},
    }
    return asyncio.run(ShoppingGuideSkill().execute(ctx))


def test_very_vague_input_triggers_clarification(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_search(monkeypatch, _MOCK_PRODUCTS)
    res = _run_guide("推荐")
    assert "男款还是女款" in res["output"]
    assert calls == [], "超模糊追问轮不得消耗检索"
    assert res["extra"]["guideContext"]["clarificationRound"] == 1


def test_second_vague_round_searches_instead_of_looping(monkeypatch: pytest.MonkeyPatch) -> None:
    """clarificationRound=1 后同样的模糊输入必须推进检索,不得无限追问。"""
    calls = _stub_search(monkeypatch, _MOCK_PRODUCTS)
    res = _run_guide("推荐", guide_ctx={"clarificationRound": 1})
    assert len(calls) == 1
    assert "推荐商品" in res["output"]


def test_preference_extraction_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_search(monkeypatch, _MOCK_PRODUCTS)
    res = _run_guide("推荐一款透气缓震的男款跑鞋")
    prefs = res["extra"]["guideContext"]["extractedPreferences"]
    assert prefs.get("gender") == "男款"
    assert prefs.get("feature") == "透气轻便"
    assert prefs.get("scenario") == "专业缓震慢跑"
    assert "男款" in res["output"], "播报须复述已识别偏好"


def test_budget_is_parsed_and_passed_to_search(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_search(monkeypatch, _MOCK_PRODUCTS)
    res = _run_guide("推荐跑鞋,预算800")
    assert calls and calls[0].get("maxPrice") == 800
    prefs = res["extra"]["guideContext"]["extractedPreferences"]
    assert prefs.get("budget") == "¥800以内"


def test_no_products_honest_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_search(monkeypatch, [])
    _stub_overview(monkeypatch, [])  # 盘点不可达 → 回落旧文案,诚实空不冷场变冷场
    res = _run_guide("推荐滑雪板")
    assert "未能找到" in res["output"]
    assert "目前店内热卖品类" not in res["output"], "盘点空不得编造品类"
    assert "cards" not in res or not res.get("cards")


def test_no_products_empty_lists_real_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    """诚实空带品类盘点(2026-09-12):不冷场,给可点选的真实店内方向。"""
    _stub_search(monkeypatch, [])
    _stub_overview(
        monkeypatch,
        [{"category": "背包收纳", "spuCount": 2}, {"category": "露营装备", "spuCount": 1}],
    )
    res = _run_guide("推荐几款背心")  # >4 字,避开超模糊追问分支,直达检索空分支
    assert "未能找到" in res["output"]
    assert "目前店内热卖品类" in res["output"]
    assert "背包收纳(2款)" in res["output"]
    assert "露营装备(1款)" in res["output"]
    assert "调整预算或关键词" not in res["output"], "有盘点时回落文案不得同时出现"


def test_candidates_contract_feeds_cart_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    """跨技能契约:导购产出的 guideContext.candidateProducts 必须能被
    CartManageSkill 的"把第N件加入购物车"直接消费。"""
    _stub_search(monkeypatch, _MOCK_PRODUCTS)
    guide_res = _run_guide("推荐几双跑鞋")
    guide_ctx = guide_res["extra"]["guideContext"]

    MallDomainService._cart_storage.pop("u_guide", None)
    cart_res = asyncio.run(
        CartManageSkill().execute(
            {
                "threadId": "t_guide",
                "tenantId": "ecommerce",
                "userId": "u_guide",
                "input": "把第2件加入购物车",
                "slots": {"activeIntent": "cart_manage"},
                "extra": {"guideContext": guide_ctx},
            }
        )
    )
    cart_map = {i["skuId"]: i["quantity"] for i in MallDomainService._cart_storage["u_guide"]}
    assert cart_map == {"prod_nike_invincible_3": 1}, "第2件 = 导购候选#2 Invincible"
    assert "Invincible" in cart_res["output"]


def test_shopping_guide_can_handle_fallback() -> None:
    skill = ShoppingGuideSkill()
    assert skill.can_handle({"input": "帮我挑一款跑鞋"}) is True
    assert skill.can_handle({"input": "查询订单状态"}) is False


# ---------------------------------------------------------------- 商品查询

class _FakeSpi:
    def __init__(self, products):
        self.products = products
        self.calls = []

    async def search_products(self, params: dict) -> list[dict]:
        self.calls.append(params)
        return self.products


def _run_inquiry(monkeypatch: pytest.MonkeyPatch, products) -> dict:
    spi = _FakeSpi(products)

    async def fake_client(self, tenant_id: str):
        return spi

    monkeypatch.setattr(ProductInquirySkill, "get_spi_client", fake_client)
    ctx = {
        "threadId": "t_inq",
        "tenantId": "ecommerce",
        "userId": "u_inq",
        "input": "Pegasus 41 有货吗",
        "slots": {"query": "Pegasus 41"},
    }
    return asyncio.run(ProductInquirySkill().execute(ctx))


def test_inquiry_lists_products_with_stock(monkeypatch: pytest.MonkeyPatch) -> None:
    # 对齐 LocalDbSpiAdapter.search_products 真实契约:title/productId/isAvailable
    spi_products = [
        {
            "productId": "prod_nike_air_pegasus_41",
            "title": "Nike Air Zoom Pegasus 41 极速轻量透气跑鞋",
            "description": "",
            "price": 899.0,
            "stock": 58,
            "category": "running_shoes",
            "isAvailable": True,
        }
    ]
    res = _run_inquiry(monkeypatch, spi_products)
    assert res["success"] is True
    assert "Pegasus 41" in res["output"]
    assert "58" in res["output"], "库存数须展示"


def test_inquiry_no_result_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_overview(monkeypatch, [])  # 盘点不可达 → 回落旧文案
    res = _run_inquiry(monkeypatch, [])
    assert "未能找到" in res["output"]


def test_inquiry_no_result_lists_real_categories(monkeypatch: pytest.MonkeyPatch) -> None:
    """查询技能空分支同款盘点:诚实空带店内真实品类(与导购空分支同源)。"""
    _stub_overview(
        monkeypatch,
        [{"category": "潮流鞋靴", "spuCount": 2}, {"category": "下装裤类", "spuCount": 1}],
    )
    res = _run_inquiry(monkeypatch, [])
    assert "未能找到" in res["output"]
    assert "目前店内热卖品类" in res["output"]
    assert "潮流鞋靴(2款)" in res["output"]
    assert "下装裤类(1款)" in res["output"]
