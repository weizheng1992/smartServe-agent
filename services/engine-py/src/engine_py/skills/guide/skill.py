"""商品导购 + 商品查询技能(薄壳)— 镜像 productInquirySkill.ts / shoppingGuideSkill.ts。

结构纪律(cart/ 先例,2026-10-07 拆解):本壳不许长业务枝 —— 词族与检索前
文本解析在 resolver,检索编排(搭配补脚/指代对比/空货架)在 recommendation,
卡与结论渲染在 cards。类上四个正则别名是 routing / 词族之家的兼容面
(同一编译对象)。
"""

from __future__ import annotations

from ...tools_registry.mall_domain import MallDomainService
from ..base_skill import BaseSkill
from ..contract import SkillContext, SkillResult
from . import cards as cards_mod
from . import recommendation, resolver


class ProductInquirySkill(BaseSkill):
    metadata = {
        "id": "skill_product_inquiry",
        "name": "商品导购与现货库存查询 SOP",
        "description": "穿透查询第三方商品目录、实时 SKU 现货库存及商品推荐",
        "category": "pre_sale",
        "triggerIntents": ["general_query"],  # A5 清死词:PRODUCT_INQUIRY/product_query/mall_search 均非注册表档位
        "requiredTools": ["searchProducts"],
        "version": "1.0.0",
    }

    async def execute(self, context: SkillContext) -> SkillResult:
        query = context.slots.get("query") or context.input or ""
        category = context.slots.get("category")

        spi_client = await self.get_spi_client(context.tenant_id)
        products = await spi_client.search_products(
            {"query": query, "category": category, "tenantId": context.tenant_id, "limit": 3}
        )

        if not products:
            # 品类盘点引导(2026-09-12):与 ShoppingGuideSkill 空分支同款,诚实空
            # 带店内真实品类方向。
            overview = await MallDomainService.get_shelf_overview()
            inventory_line = (
                "、".join(f"{o['category']}({o['spuCount']}款)" for o in overview) if overview else ""
            )
            output = f'抱歉，未能找到与"{query}"相关的商品。'
            output += (
                f"\n目前店内热卖品类：{inventory_line}，欢迎换个叫法或从这些品类挑挑看！"
                if inventory_line
                else "您可以尝试更换关键词或咨询在线客服。"
            )
            return SkillResult(skill_id=self.metadata["id"], output=output)

        # 规格问句直答(2026-09-12):「有什么规格/尺码/颜色」类问句,检索首位
        # 商品命中即直查真货架 SKU 出参(real-data-only/01 残余项③)—— 不再
        # 只列商品让用户再问一轮;查无/查询异常回落列表形态,不阻断。
        top_id = products[0].get("productId") if products else None
        if resolver.SPEC_ASK_RE.search(query) and top_id:
            top = products[0]
            try:
                sku_res = await MallDomainService.query_product_skus({"productId": top_id})
            except Exception as sku_err:
                print(f"[ProductInquirySkill] SKU 查询失败,回落商品列表: {sku_err}")
                sku_res = None
            skus = (sku_res or {}).get("skus") or []
            if skus:
                spec_lines = "\n".join(
                    f"• {self._format_spec(s.get('specs'))} — {s['price']}"
                    f"（{'现货' if s.get('inStock') else '缺货'}）"
                    for s in skus
                )
                return SkillResult(
                    skill_id=self.metadata["id"],
                    output=(
                        f"为您找到【{top.get('title')}】，可选规格如下：\n{spec_lines}\n\n"
                        "如需把某一款加入购物车或了解详情，请随时告诉我！"
                    ),
                )

        product_summary = "\n\n".join(
            self._format_product(p) for p in products
        )
        return SkillResult(
            skill_id=self.metadata["id"],
            output=f"为您找到以下相关商品：\n{product_summary}\n\n如需了解具体尺码规格或下单，请随时告诉我！",
        )

    @staticmethod
    def _format_spec(specs: dict | None) -> str:
        if not specs:
            return "标准款"
        return " / ".join(f"{v}" for v in specs.values()) or "标准款"

    @staticmethod
    def _format_product(p: dict) -> str:
        stock = p.get("stock") or 0
        text = f"• 【{p.get('title')}】 (¥{p.get('price')}) - 总库存: {f'{stock}件现货' if stock > 0 else '暂时缺货'}"
        if p.get("specDimensions"):
            dims = " | ".join(f"{d['name']}: {'/'.join(d['values'])}" for d in p["specDimensions"])
            text += f"\n   📐 可选规格: {dims}"
        if p.get("specs"):
            spec_entries = "；".join(f"{k}:{v}" for k, v in list(p["specs"].items())[:2])
            text += f"\n   🔬 核心参数: {spec_entries}"
        return text


class ShoppingGuideSkill(BaseSkill):
    metadata = {
        "id": "skill_shopping_guide",
        "name": "商品智能导购与选品推荐 Agent SOP",
        "description": "多轮偏好挖掘、商品库深度检索、多维参数比对与候选集维护",
        "category": "pre_sale",
        "triggerIntents": ["shopping_guide", "general_query"],  # A5 清死词:product_query/PRODUCT_INQUIRY 非注册表档位
        "requiredTools": ["searchProducts", "compareProducts", "queryProductSkus"],
        "version": "1.0.0",
    }

    # 兼容别名(同一编译对象,单一事实源在 guide.resolver):routing.reroute_tool
    # 与词族之家测试经类属性消费 —— 严禁此处另编译,漂移即双源。
    _FALLBACK_RE = resolver.GUIDE_FALLBACK_RE
    _ABSENCE_ANCHOR_RE = resolver.ABSENCE_ANCHOR_RE
    OUTFIT_RE = resolver.OUTFIT_RE
    CLOTHING_ANCHOR_RE = resolver.CLOTHING_ANCHOR_RE

    def can_handle(self, context: SkillContext) -> bool:
        if super().can_handle(context):
            return True
        user_input = context.input.lower()
        if resolver.NEGATIVE_INTENT_RE.search(user_input):
            return False
        return bool(resolver.GUIDE_FALLBACK_RE.search(user_input))

    async def execute(self, context: SkillContext) -> SkillResult:
        user_input = context.input.strip()
        existing_guide = context.guide_context or {}
        carried_prefs: dict = {**(existing_guide.get("extractedPreferences") or {})}
        clarification_round = existing_guide.get("clarificationRound") or 0

        # 0. 缺席反问/承接式反问剥框(先于一切搜索):「没有衣服呢」「不用帐篷
        # 吗」→ 直查品类名词。检索词与空分支措辞都换成品类名词,严禁把顾客
        # 反问原话当搜索描述引用;承接语的数量词(「两件」指上轮)不是本次
        # 推荐数量,命中后跳过数量解析。
        absence_topic, absence_rhetoric = resolver.detect_absence(user_input)

        # 1. 偏好特征提取(命中即记 touched = 本轮实际说出的偏好键);颜色真折
        # 进检索(2026-10-01 实弹「我喜欢黑色…」):经 search_products color 参数
        # 走 catalog_match 的 SKU spec 级 EXISTS;承接面旧颜色照旧严禁折入
        # (对齐 2026-09-30 陈旧偏好契约)。本轮实际说出的偏好才上展示句
        # (2026-09-30 实弹:昨日旅行 2500 预算混进今日「出去游玩」推荐语 =
        # 广告出没有发生的结合)。
        new_prefs, touched, max_price = resolver.extract_preferences(user_input)
        extracted_prefs: dict = {**carried_prefs, **new_prefs}
        current_turn_prefs = {k: new_prefs[k] for k in touched}
        color_pref = current_turn_prefs.get("color")

        # 2. 超模糊查询多轮追问
        if resolver.is_very_vague(
            user_input,
            max_price=max_price,
            extracted_prefs=extracted_prefs,
            clarification_round=clarification_round,
        ):
            clarification_round += 1
            return SkillResult(
                skill_id=self.metadata["id"],
                output=(
                    "您好！我是您的专属选品顾问。请问您这次选购是男款还是女款？"
                    "主要用于日常通勤还是专业运动跑步呢？告诉我您的偏好或预算，我将为您精准挑选！✨"
                ),
                guide_context={"extractedPreferences": extracted_prefs, "clarificationRound": clarification_round},
            )

        # 3. 商品检索与推荐(主检索 + 搭配族缺补脚)
        limit = resolver.parse_requested_limit(user_input, absence_rhetoric)
        products, outfit_gap_note = await recommendation.search_with_outfit_fill(
            user_input=user_input,
            absence_topic=absence_topic,
            max_price=max_price,
            color_pref=color_pref,
            limit=limit,
            tenant_id=context.tenant_id,
            thread_id=context.thread_id,
        )

        if not products:
            # 上下文指代式对比/价位带重检(有上轮检索词才成立),否则诚实空。
            # 对比面(≥2 档)照旧携带偏好承接与轮次;价位带面不带(原样)
            compare = await recommendation.price_band_compare(
                user_input=user_input,
                existing_guide=existing_guide,
                tenant_id=context.tenant_id,
                thread_id=context.thread_id,
                extracted_prefs=extracted_prefs,
                clarification_round=clarification_round,
            )
            if compare is not None:
                return compare
            return SkillResult(
                skill_id=self.metadata["id"],
                output=await recommendation.empty_shelf_output(absence_topic=absence_topic, user_input=user_input),
            )

        # 4. 组装商品卡片与推荐语(合计确定性算出,finish 只许转述不许编)
        cards = [cards_mod.build_ranking_card(products)]
        product_summary_text = "\n\n".join(cards_mod.format_candidate(p, idx) for idx, p in enumerate(products))
        pref_summary = (
            f"（已结合您的偏好：{'、'.join(current_turn_prefs.values())}）" if current_turn_prefs else ""
        )
        total_line = cards_mod.budget_total_line(products, max_price)

        if absence_topic:
            output = (
                f"有的！店内这些{absence_topic}在售：\n\n{product_summary_text}{total_line}\n\n"
                "如需把某件加入购物车，直接对我说“把第几件加入购物车”即可！🛒"
            )
        else:
            output = (
                f"为您精选了以下推荐商品{pref_summary}：\n\n{product_summary_text}{total_line}{outfit_gap_note}\n\n"
                "如需加入购物车，直接对我说“把第几件加入购物车”即可！🛒"
            )

        guide_context = {
            "candidateProductIds": [p["id"] for p in products],
            "candidateProducts": [
                {
                    "id": p["id"],
                    "name": p["name"],
                    "price": float(p.get("price") or 0),
                    "stock": int(p.get("stock") or 0),
                    "description": p.get("description"),
                    "specs": p.get("specs"),
                    "imageUrl": p.get("imageUrl"),
                }
                for p in products
            ],
            "extractedPreferences": extracted_prefs,
            "clarificationRound": clarification_round + 1,
            "lastSearchQuery": absence_topic or user_input,
        }
        return SkillResult(
            skill_id=self.metadata["id"],
            output=output,
            cards=cards,
            guide_context=guide_context,
        )
