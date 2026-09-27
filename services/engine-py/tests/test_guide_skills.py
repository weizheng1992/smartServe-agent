"""导购技能回归:偏好提取/超模糊追问/预算过滤/空结果/候选契约,
以及 导购 ➔ 购物车 跨技能候选传递闭环。

search_products 以桩注入保证确定性(skill 层编排契约);
MallDomainService 检索语义另由 mall 相关测试钉。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.skills.cart import CartManageSkill
from engine_py.skills.contract import SkillContext
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
    ctx = SkillContext(
        thread_id="t_guide",
        tenant_id="ecommerce",
        user_id="u_guide",
        input=text,
        guide_context=guide_ctx or {},
    )
    return asyncio.run(ShoppingGuideSkill().execute(ctx)).to_dict()


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
            SkillContext(
                thread_id="t_guide",
                tenant_id="ecommerce",
                user_id="u_guide",
                input="把第2件加入购物车",
                slots={"activeIntent": "cart_manage"},
                guide_context=guide_ctx,
            )
        )
    ).to_dict()
    cart_map = {i["skuId"]: i["quantity"] for i in MallDomainService._cart_storage["u_guide"]}
    assert cart_map == {"prod_nike_invincible_3": 1}, "第2件 = 导购候选#2 Invincible"
    assert "Invincible" in cart_res["output"]


def test_shopping_guide_can_handle_fallback() -> None:
    skill = ShoppingGuideSkill()
    assert skill.can_handle(SkillContext(input="帮我挑一款跑鞋")) is True
    assert skill.can_handle(SkillContext(input="查询订单状态")) is False


def test_guide_card_carries_no_fabricated_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """推荐卡诚实性(2026-09-12):商户货架无销量/GMV/毛利数据,严禁合成
    (对齐 2.6.8 铁律)——旧卡编造 totalGmv=价格×100、grossProfit=价格×40%、
    marginRate='40%'、totalVolume 兜底 100,前端照实展示欺骗用户。"""
    _stub_search(monkeypatch, _MOCK_PRODUCTS)
    res = _run_guide("推荐几双跑鞋")
    card = next(c for c in res["cards"] if c["type"] == "product_ranking")
    for p in card["data"]["products"]:
        for fabricated in ("totalVolume", "totalGmv", "grossProfit", "marginRate"):
            assert fabricated not in p, f"推荐卡不得编造 {fabricated}"
        assert p["metricDisplay"], "仅允许真实字段+推荐位次文案"
        assert p["price"] > 0


# ---------------------------------------------------------------- 商品查询

class _FakeSpi:
    def __init__(self, products):
        self.products = products
        self.calls = []

    async def search_products(self, params: dict) -> list[dict]:
        self.calls.append(params)
        return self.products


def _run_inquiry(
    monkeypatch: pytest.MonkeyPatch, products, input_text: str = "Pegasus 41 有货吗", query: str = "Pegasus 41"
) -> dict:
    spi = _FakeSpi(products)

    async def fake_client(self, tenant_id: str):
        return spi

    monkeypatch.setattr(ProductInquirySkill, "get_spi_client", fake_client)
    ctx = SkillContext(
        thread_id="t_inq",
        tenant_id="ecommerce",
        user_id="u_inq",
        input=input_text,
        slots={"query": query},
    )
    return asyncio.run(ProductInquirySkill().execute(ctx)).to_dict()


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

def test_inquiry_spec_ask_lists_real_skus(monkeypatch: pytest.MonkeyPatch) -> None:
    """规格问句(2026-09-12):问「有什么规格」直答真货架 SKU,不再只列商品
    让用户再问一轮(实测「双肩包有什么规格」曾空转)。"""
    spi_products = [
        {
            "productId": "SPU-P-BAG",
            "title": "极光 城市通勤双肩包",
            "description": "通勤双肩包",
            "price": 499.0,
            "stock": 42,
            "isAvailable": 1,
        }
    ]
    sku_payload = {
        "total": 2,
        "productId": "SPU-P-BAG",
        "skus": [
            {
                "skuId": "SPU-P-BAG-SKU-M",
                "skuCode": "SPU-P-BAG-SKU-M",
                "productName": "极光 城市通勤双肩包",
                "specs": {"color": "曜石黑", "size": "15寸"},
                "price": "¥499.00",
                "stock": 30,
                "inStock": True,
                "status": "ON_SALE",
            },
            {
                "skuId": "SPU-P-BAG-SKU-L",
                "skuCode": "SPU-P-BAG-SKU-L",
                "productName": "极光 城市通勤双肩包",
                "specs": {"color": "雾岩灰", "size": "17寸"},
                "price": "¥549.00",
                "stock": 0,
                "inStock": False,
                "status": "ON_SALE",
            },
        ],
    }

    async def fake_skus(params: dict) -> dict:
        return sku_payload

    monkeypatch.setattr(MallDomainService, "query_product_skus", staticmethod(fake_skus))
    res = _run_inquiry(monkeypatch, spi_products, input_text="双肩包有什么规格", query="双肩包 规格")
    out = res["output"]
    assert "可选规格" in out, f"规格问句应直答 SKU: {out}"
    assert "曜石黑" in out and "¥499.00" in out, f"应带真规格与价格: {out}"
    assert "雾岩灰" in out and "缺货" in out, f"缺货规格也应如实列出: {out}"


def test_inquiry_non_spec_ask_keeps_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    """非规格问句保持原列表形态,不触发 SKU 查询。"""
    spi_products = [
        {"productId": "SPU-X", "title": "某商品", "description": "", "price": 99.0, "stock": 3, "isAvailable": 1}
    ]
    called: list[dict] = []

    async def fake_skus(params: dict) -> dict:
        called.append(params)
        return {"total": 0, "skus": []}

    monkeypatch.setattr(MallDomainService, "query_product_skus", staticmethod(fake_skus))
    res = _run_inquiry(monkeypatch, spi_products, input_text="有没有便宜的背包", query="便宜的背包")
    assert called == [], "非规格问句不得触达 SKU 查询"
    assert "为您找到以下相关商品" in res["output"]



# ---------- 搭配族缺补脚 + 合计预算诚实 + 缺席反问(2026-09-27 实弹事故) ----------
# 事故:旅行搭配请求单脚整句检索,「装备」ILIKE 命中品类列「露营装备」吃满
# limit(3 件露营装备零衣服),「衣服」货架零词法足迹;合计 2527 无人计算,
# finish 却宣称「总价不超过2000元」;追问「没有衣服呢」被当字面搜索词。

_GEAR = {
    "id": "g_tent",
    "name": "极光 轻量化双人双层露营帐篷",
    "price": 1299.0,
    "stock": 73,
    "description": "3分钟快搭",
    "specs": {"防水": "3000mm"},
    "category": "露营装备",
}
_CLOTHES = [
    {"id": "c_polo", "name": "极光 凉感抗菌速干机能POLO衫", "price": 269.0, "stock": 50, "description": "凉感速干", "specs": {}, "category": "潮流T恤"},
    {"id": "c_shirt", "name": "极光 120g超轻可收纳防晒皮肤短袖衬衫", "price": 329.0, "stock": 40, "description": "UPF40+", "specs": {}, "category": "衬衫"},
]


def _stub_dual_family_search(monkeypatch: pytest.MonkeyPatch, gear: list[dict], clothes: list[dict]) -> list[dict]:
    """按查询内容分流的双族桩:整句(含装备)→ 露营族;裸锚词 → 衣着族。
    复刻真货架词法:装备硬命中、衣服零足迹靠 L2 语义才落族。"""
    calls: list[dict] = []

    async def fake_search(params: dict) -> dict:
        calls.append(params)
        if "装备" in (params.get("query") or ""):
            return {"total": len(gear), "products": list(gear)}
        return {"total": len(clothes), "products": list(clothes)}

    monkeypatch.setattr(MallDomainService, "search_products", staticmethod(fake_search))
    return calls


def test搭配请求补脚衣着族并报真实合计(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_dual_family_search(monkeypatch, [_GEAR], _CLOTHES)
    res = _run_guide("我打算出去旅行，给我搭配一套出去旅行的装备和衣服，按照现在的季节，金额不超过2000")
    out = res["output"]
    assert len(calls) == 2 and calls[1]["query"] == "衣服", "衣着族必须以裸锚词补一脚"
    assert "POLO衫" in out and "衬衫" in out, "推荐必须双族在场,禁止单族冒充一套"
    assert "¥1897" in out, "合计必须确定性计算:1299+269+329=1897"
    assert "在您 ¥2000 预算内" in out
    ids = [p["id"] for p in res["extra"]["guideContext"]["candidateProducts"]]
    assert ids == ["g_tent", "c_polo", "c_shirt"], "候选序必须与播报编号一致(购物车第N件契约)"


def test搭配合计超预算如实告知(monkeypatch: pytest.MonkeyPatch) -> None:
    gear = [_GEAR, {**_GEAR, "id": "g_bag", "name": "极光 高山徒步轻量化背包", "price": 899.0}]
    clothes = [
        _CLOTHES[0],
        {**_CLOTHES[1], "id": "c_jacket", "name": "极光 三合一全天候户外硬壳冲锋衣", "price": 899.0},
    ]
    _stub_dual_family_search(monkeypatch, gear, clothes)
    res = _run_guide("给我搭配一套旅行装备和衣服，金额不超过2000")
    out = res["output"]
    assert "已超出您 ¥2000 预算" in out, "超预算必须如实说,严禁宣称在预算内"
    assert "¥3366" in out, "合计必须确定性计算:交错合并4件 1299+269+899+899=3366"


def test缺席反问剥否定直查品类(monkeypatch: pytest.MonkeyPatch) -> None:
    """「没有衣服呢」是指出上轮推荐缺衣着族,不是字面搜索词 —— 剥否定框以
    裸词「衣服」直查,播报在售真货,严禁引用顾客反问原话当搜索描述。"""
    calls: list[dict] = []

    async def fake_search(params: dict) -> dict:
        calls.append(params)
        return {"total": len(_CLOTHES), "products": list(_CLOTHES)}

    monkeypatch.setattr(MallDomainService, "search_products", staticmethod(fake_search))
    res = _run_guide("没有衣服呢")
    assert calls and calls[0]["query"] == "衣服", "必须剥掉否定框只查品类名词"
    out = res["output"]
    assert "有的" in out and "衣服" in out
    assert "POLO衫" in out
    assert "没有衣服呢" not in out, "顾客反问原话不得被当搜索描述引用"


def test缺席反问查无以品类名词如实作答(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺席框命中但货架真无该族(袜子)→ 以品类名词如实作答 + 品类盘点,
    严禁引用「没有袜子呢」原话当搜索描述。"""
    calls = _stub_search(monkeypatch, [])
    _stub_overview(monkeypatch, [{"category": "衬衫", "spuCount": 4}])
    res = _run_guide("没有袜子呢")
    assert calls and calls[0]["query"] == "袜子"
    assert "店内暂时没有袜子在售" in res["output"]
    assert "目前店内热卖品类" in res["output"]
    assert "没有袜子呢" not in res["output"]


def test缺席反问订单域负句不劫持(monkeypatch: pytest.MonkeyPatch) -> None:
    """「没有收到货」无购物锚词 → 不剥框,整句照常进检索(该轮本应路由
    订单域,此处只验证技能层不做错误劫持)。"""
    calls = _stub_search(monkeypatch, [])
    _stub_overview(monkeypatch, [])
    _run_guide("没有收到货")
    assert calls and calls[0]["query"] == "没有收到货"


def test常规推荐给出合计与预算结论(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_search(monkeypatch, _MOCK_PRODUCTS)  # 899+1299+599=2797
    res = _run_guide("推荐跑鞋,预算800")
    out = res["output"]
    assert "¥2797" in out and "已超出您 ¥800 预算" in out, "合计与超预算结论必须如实"
    assert calls[0].get("maxPrice") == 800


def test常规推荐预算内给正向结论(monkeypatch: pytest.MonkeyPatch) -> None:
    cheap = [
        {"id": "cheap1", "name": "极光 速干无缝多功能魔术头巾围脖", "price": 39.0, "stock": 100, "description": "速干", "specs": {}, "category": "配饰"},
        {"id": "cheap2", "name": "极光 宽檐透气可调节防晒空顶帽", "price": 79.0, "stock": 80, "description": "防晒", "specs": {}, "category": "配饰"},
    ]
    _stub_search(monkeypatch, cheap)
    res = _run_guide("推荐防晒配饰,预算200")
    assert "合计 ¥118" in res["output"] and "在您 ¥200 预算内" in res["output"]


def test搭配首脚已含衣着不补脚(monkeypatch: pytest.MonkeyPatch) -> None:
    """首脚命中已含衣着商品(品类均衡)→ 不再补第二脚,检索一次。"""
    mixed = [
        {**_GEAR, "id": "g1"},
        {"id": "c1", "name": "极光 亚麻混纺透气度假休闲短袖衬衫", "price": 379.0, "stock": 30, "description": "透气", "specs": {}, "category": "衬衫"},
    ]
    calls = _stub_dual_family_search(monkeypatch, mixed, _CLOTHES)
    _run_guide("给我搭配一套旅行装备和衣服，金额不超过2000")
    assert len(calls) == 1, "衣着已在场则禁发补脚检索"
