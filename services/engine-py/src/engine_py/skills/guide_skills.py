"""商品导购 + 商品查询技能 — 镜像 productInquirySkill.ts / shoppingGuideSkill.ts。"""

from __future__ import annotations

import re

from ..tools_registry.mall_domain import MallDomainService
from .base_skill import BaseSkill

# 规格问句识别(2026-09-12):命中即对检索首位商品直查真货架 SKU
_SPEC_ASK_RE = re.compile(r"(规格|尺码|尺寸|颜色|码数|参数|型号)")


class ProductInquirySkill(BaseSkill):
    metadata = {
        "id": "skill_product_inquiry",
        "name": "商品导购与现货库存查询 SOP",
        "description": "穿透查询第三方商品目录、实时 SKU 现货库存及商品推荐",
        "category": "pre_sale",
        "triggerIntents": ["PRODUCT_INQUIRY", "product_query", "general_query", "mall_search"],
        "requiredTools": ["searchProducts"],
        "version": "1.0.0",
    }

    async def execute(self, context: dict) -> dict:
        slots = context.get("slots") or {}
        query = slots.get("query") or context.get("input") or ""
        category = slots.get("category")

        spi_client = await self.get_spi_client(context.get("tenantId", "ecommerce"))
        products = await spi_client.search_products(
            {"query": query, "category": category, "tenantId": context.get("tenantId", "ecommerce"), "limit": 3}
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
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": output,
                "nextAction": "finish",
            }

        # 规格问句直答(2026-09-12):「有什么规格/尺码/颜色」类问句,检索首位
        # 商品命中即直查真货架 SKU 出参(real-data-only/01 残余项③)—— 不再
        # 只列商品让用户再问一轮;查无/查询异常回落列表形态,不阻断。
        top_id = products[0].get("productId") if products else None
        if _SPEC_ASK_RE.search(query) and top_id:
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
                return {
                    "success": True,
                    "skillId": self.metadata["id"],
                    "output": (
                        f"为您找到【{top.get('title')}】，可选规格如下：\n{spec_lines}\n\n"
                        "如需把某一款加入购物车或了解详情，请随时告诉我！"
                    ),
                    "nextAction": "finish",
                }

        product_summary = "\n\n".join(
            self._format_product(p) for p in products
        )
        return {
            "success": True,
            "skillId": self.metadata["id"],
            "output": f"为您找到以下相关商品：\n{product_summary}\n\n如需了解具体尺码规格或下单，请随时告诉我！",
            "nextAction": "finish",
        }

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
        "triggerIntents": ["shopping_guide", "general_query", "product_query", "PRODUCT_INQUIRY"],
        "requiredTools": ["searchProducts", "compareProducts", "queryProductSkus"],
        "version": "1.0.0",
    }

    # 与 slot_extractor 的 SHOPPING_GUIDE 规则同源补词(2026-09-07):热门/爆款类
    # 措辞也须被 is_action_query 视作动作形输入,拒绝命中语义回复缓存。
    # 2026-09-12:补入 卖得好/卖的好(与 slot_extractor 同步,见该处注释)。
    _FALLBACK_RE = re.compile(
        r"(?:推荐|买什么|挑一款|选一款|好看|款式|选鞋|选衣服|哪款好|跑步鞋|卫衣|夹克|热门|爆款|热销|热卖|畅销|上新|新品|卖得好|卖的好"
        r"|最便宜|便宜点|最贵|性价比|哪个好|怎么选|有什么区别|买哪种|该用什么|需要准备什么"
        r"|背什么|用哪种|什么包)",
        re.IGNORECASE,
    )

    # 否定购买意向(2026-09-14 N2 实报):「我不想买了/别推荐」严禁再搜索推荐
    _NEGATIVE_INTENT_RE = re.compile(r"(?:不想买|别.{0,2}推荐|不要推荐|不再推荐|停止推荐)")

    def can_handle(self, context: dict) -> bool:
        if super().can_handle(context):
            return True
        user_input = (context.get("input") or "").lower()
        if self._NEGATIVE_INTENT_RE.search(user_input):
            return False
        return bool(self._FALLBACK_RE.search(user_input))

    async def execute(self, context: dict) -> dict:
        user_input = (context.get("input") or "").strip()
        existing_guide = (context.get("extra") or {}).get("guideContext") or {}
        extracted_prefs: dict = {**(existing_guide.get("extractedPreferences") or {})}
        clarification_round = existing_guide.get("clarificationRound") or 0

        # 1. 偏好特征提取
        if re.search(r"男|男生|男款", user_input, re.IGNORECASE):
            extracted_prefs["gender"] = "男款"
        if re.search(r"女|女生|女款", user_input, re.IGNORECASE):
            extracted_prefs["gender"] = "女款"
        if re.search(r"透气|清爽|夏", user_input, re.IGNORECASE):
            extracted_prefs["feature"] = "透气轻便"
        if re.search(r"缓震|护膝|慢跑|马", user_input, re.IGNORECASE):
            extracted_prefs["scenario"] = "专业缓震慢跑"
        if re.search(r"黑|白|红", user_input):
            color_match = re.search(r"(?:黑|白|红|蓝|灰)色?", user_input)
            if color_match:
                extracted_prefs["color"] = color_match.group(0)

        budget_match = re.search(r"(?:预算|低于|不超过|最高|价位)\s*(\d+)", user_input)
        max_price = None
        if budget_match:
            max_price = int(budget_match.group(1))
            extracted_prefs["budget"] = f"¥{max_price}以内"

        # 2. 超模糊查询多轮追问
        is_very_vague = (
            len(user_input) <= 4
            and not max_price
            and not extracted_prefs.get("scenario")
            and not extracted_prefs.get("gender")
            and clarification_round == 0
            and bool(re.search(r"(?:买东西|买鞋|买衣服|推荐|逛逛)", user_input, re.IGNORECASE))
        )
        if is_very_vague:
            clarification_round += 1
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": (
                    "您好！我是您的专属选品顾问。请问您这次选购是男款还是女款？"
                    "主要用于日常通勤还是专业运动跑步呢？告诉我您的偏好或预算，我将为您精准挑选！✨"
                ),
                "nextAction": "finish",
                "extra": {
                    "guideContext": {"extractedPreferences": extracted_prefs, "clarificationRound": clarification_round}
                },
            }

        # 3. 商品检索与推荐
        # 数量语义(2026-09-12 用户实报「我要2个商品」被无视):「N个/N件」
        # 显式数量 → 推荐 N 款(上限 8,与品类快捷区一致);「几件/几款」
        # 或未提 → 维持默认 3。
        requested_count = re.search(r"([2-9]|1[0]|两|三|四|五|六|七|八|九|十)\s*[个件款条双只]", user_input)
        limit = 3
        if requested_count:
            raw = requested_count.group(1)
            cn = {"两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            limit = int(raw) if raw.isdigit() else cn.get(raw, 3)
            limit = max(1, min(limit, 8))
        search_res = await MallDomainService.search_products(
            {
                "query": user_input,
                "maxPrice": max_price,
                "limit": limit,
                "businessId": context.get("tenantId"),
                "threadId": context.get("threadId"),
            }
        )
        products = search_res.get("products") or []
        candidate_product_ids = [p["id"] for p in products]

        if not products:
            # 品类盘点引导(2026-09-12):诚实空不冷场 —— 告诉用户店里实际有什么,
            # 「卖得好」类模糊词落空时给可点选的真实方向,而非一句调整关键词。
            overview = await MallDomainService.get_shelf_overview()
            inventory_line = (
                "、".join(f"{o['category']}({o['spuCount']}款)" for o in overview) if overview else ""
            )
            output = f'抱歉，暂时未能找到完全符合"{user_input}"的现货商品。'
            output += (
                f"\n目前店内热卖品类：{inventory_line}，欢迎换个叫法或从这些品类挑挑看！"
                if inventory_line
                else "建议您可以调整预算或关键词再试一次！"
            )
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": output,
                "nextAction": "finish",
            }

        # 4. 组装商品卡片
        # 诚实性(ADR-0002 数据条件禁令):商户货架无销量数据,推荐卡严禁
        # 「热销」字样与编造分数(metricScore=99-idx*5 已拆)——只带真实
        # 字段(价格/现货/品类)+ 推荐位次;rankingMetric=recommendation
        # 让卡合成器识别为推荐卡而非真排行(不触发统计口径消歧组)。
        cards = [
            {
                "type": "product_ranking",
                "data": {
                    "rankingMetric": "recommendation",
                    "metricLabel": "为您推荐",
                    "itemCount": len(products),
                    "summary": f"为您精选 {len(products)} 款现货商品",
                    "products": [
                        {
                            "rank": idx + 1,
                            "productId": p["id"],
                            "name": p["name"],
                            "category": p.get("category") or "精选现货",
                            "price": float(p.get("price") or 0),
                            "stock": int(p.get("stock") or 0),
                            "metricDisplay": "店长精选" if idx == 0 else f"推荐 No.{idx + 1}",
                        }
                        for idx, p in enumerate(products)
                    ],
                },
            }
        ]

        product_summary_text = "\n\n".join(self._format_candidate(p, idx) for idx, p in enumerate(products))
        pref_summary = (
            f"（已结合您的偏好：{'、'.join(extracted_prefs.values())}）" if extracted_prefs else ""
        )
        output = (
            f"为您精选了以下推荐商品{pref_summary}：\n\n{product_summary_text}\n\n"
            "如需加入购物车，直接对我说“把第几件加入购物车”即可！🛒"
        )

        guide_context = {
            "candidateProductIds": candidate_product_ids,
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
            "lastSearchQuery": user_input,
        }
        return {
            "success": True,
            "skillId": self.metadata["id"],
            "output": output,
            "cards": cards,
            "nextAction": "finish",
            "extra": {"guideContext": guide_context},
        }

    @staticmethod
    def _format_candidate(p: dict, idx: int) -> str:
        text = f"{idx + 1}. 【{p['name']}】 ¥{p.get('price')} (现货 {p.get('stock')} 件)\n   💡 {p.get('description')}"
        if p.get("specs"):
            spec_str = " | ".join(f"{k}:{v}" for k, v in p["specs"].items())
            text += f"\n   📐 特点: {spec_str}"
        return text
