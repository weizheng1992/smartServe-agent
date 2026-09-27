"""商品导购 + 商品查询技能 — 镜像 productInquirySkill.ts / shoppingGuideSkill.ts。"""

from __future__ import annotations

import re

from ..tools_registry.mall_domain import MallDomainService
from .base_skill import BaseSkill
from .contract import SkillContext, SkillResult

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
        "triggerIntents": ["shopping_guide", "general_query", "product_query", "PRODUCT_INQUIRY"],
        "requiredTools": ["searchProducts", "compareProducts", "queryProductSkus"],
        "version": "1.0.0",
    }

    # 与 slot_extractor 的 SHOPPING_GUIDE 规则同源补词(2026-09-07):热门/爆款类
    # 措辞也须被 is_action_query 视作动作形输入,拒绝命中语义回复缓存。
    # 2026-09-12:补入 卖得好/卖的好(与 slot_extractor 同步,见该处注释)。
    # 上下文指代式对比(2026-09-14):「最贵的和最便宜的对比」—— 无品类词,
    # 指代上一轮检索
    _COMPARE_RE = re.compile(r"(?:对比|不同|差别|区别|比一比)")

    # 价位带指代(S5,2026-09-15):「有没有中间价位的」—— 无品类词指代上轮
    _PRICE_BAND_RE = re.compile(r"(?:中间价位|中间价|价位段|中等价位)")

    _FALLBACK_RE = re.compile(
        r"(?:推荐|买什么|挑一款|选一款|好看|款式|选鞋|选衣服|哪款好|跑步鞋|卫衣|夹克|热门|爆款|热销|热卖|畅销|上新|新品|卖得好|卖的好"
        r"|最便宜|便宜点|最贵|性价比|哪个好|怎么选|有什么区别|买哪种|该用什么|需要准备什么"
        r"|背什么|用哪种|什么包)",
        re.IGNORECASE,
    )

    # 否定购买意向(2026-09-14 N2 实报):「我不想买了/别推荐」严禁再搜索推荐
    _NEGATIVE_INTENT_RE = re.compile(r"(?:不想买|别.{0,2}推荐|不要推荐|不再推荐|停止推荐)")

    # 🧳 搭配形态(2026-09-27 实弹事故):「搭配一套…装备和衣服」是多族组合
    # 诉求。单脚整句检索下「装备」ILIKE 命中品类列「露营装备」即把 limit 全部
    # 吃满(3 件露营装备零衣服),而「衣服」在货架零词法足迹(货架以 衬衫/
    # T恤/裤/夹克 命名),硬命中非空又令 L2 语义补位永不触发 —— 族缺口必须
    # 以裸锚词补一脚(裸词「衣服」经 L2 语义实测正确落 T恤/衬衫)。
    _OUTFIT_RE = re.compile(r"(?:搭配|一套|套装|一整套)")

    # 衣着族锚词:输入命中 = 有衣着诉求;商品名命中 = 该商品属衣着族。
    # ⚠️ 孪生词表:skills/cart/resolver.py 同族词表各自维护,改这里须查彼处。
    _CLOTHING_ANCHOR_RE = re.compile(r"衣服|服装|衣着|上衣|外套|裤子|衬衫|夹克|羽绒服|T恤|裤|鞋|靴|衫|帽|袜")

    # 缺席反问(2026-09-27 实弹事故):「没有衣服呢」是顾客指出上轮推荐缺了
    # 某族,不是新的字面搜索词 —— 整句直查词元「没有衣服」必然诚实空,空分支
    # 再把原话当描述引用(「未能找到符合“没有衣服呢”」)二次伤害。剥否定框
    # 取品类名词直查;仅当名词含购物锚词才劫持,订单域负句(「没有收到货」)
    # 不劫持(那些轮次本不该路由到本技能,防御纵深)。
    _ABSENCE_RE = re.compile(r"^(?:怎么|是不是)?没有(.+?)[呢吗么嘛]?\s*[？?]?\s*$")
    _ABSENCE_ANCHOR_RE = re.compile(
        r"衣服|服装|衣着|上衣|外套|裤子|衬衫|夹克|羽绒服|T恤|裤|鞋|靴|衫|帽|袜|配饰|背包|书包|装备|帐篷|睡袋|垫|包"
    )

    def can_handle(self, context: SkillContext) -> bool:
        if super().can_handle(context):
            return True
        user_input = context.input.lower()
        if self._NEGATIVE_INTENT_RE.search(user_input):
            return False
        return bool(self._FALLBACK_RE.search(user_input))

    async def execute(self, context: SkillContext) -> SkillResult:
        user_input = context.input.strip()
        existing_guide = context.guide_context or {}
        extracted_prefs: dict = {**(existing_guide.get("extractedPreferences") or {})}
        clarification_round = existing_guide.get("clarificationRound") or 0

        # 0. 缺席反问剥否定(先于一切搜索):「没有衣服呢」→ 直查「衣服」。
        # 检索词与空分支措辞都换成品类名词,严禁把顾客反问原话当搜索描述引用。
        absence_topic: str | None = None
        absence_m = self._ABSENCE_RE.match(user_input)
        if absence_m:
            noun = absence_m.group(1).strip()
            if noun and self._ABSENCE_ANCHOR_RE.search(noun):
                absence_topic = noun

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
            return SkillResult(
                skill_id=self.metadata["id"],
                output=(
                    "您好！我是您的专属选品顾问。请问您这次选购是男款还是女款？"
                    "主要用于日常通勤还是专业运动跑步呢？告诉我您的偏好或预算，我将为您精准挑选！✨"
                ),
                guide_context={"extractedPreferences": extracted_prefs, "clarificationRound": clarification_round},
            )

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
                "query": absence_topic or user_input,
                "maxPrice": max_price,
                "limit": limit,
                "businessId": context.tenant_id,
                "threadId": context.thread_id,
            }
        )
        products = search_res.get("products") or []

        # 🧳 搭配族缺补脚(2026-09-27 实弹事故):输入含衣着锚词而首脚命中零
        # 衣着商品(「装备」凭品类列子串吃满 limit)→ 以裸锚词补一脚,两脚
        # 交错合并(装备×衣着交替,截断也保两族在场)。补脚仍空 → 如实标注
        # 店内无该族,严禁静默只推单族冒充「一套」。
        outfit_gap_note = ""
        if (
            products
            and absence_topic is None
            and self._OUTFIT_RE.search(user_input)
            and self._CLOTHING_ANCHOR_RE.search(user_input)
            and not any(self._CLOTHING_ANCHOR_RE.search(str(p.get("name") or "")) for p in products)
        ):
            anchor = self._CLOTHING_ANCHOR_RE.search(user_input).group(0)
            second_res = await MallDomainService.search_products(
                {
                    "query": anchor,
                    "maxPrice": max_price,
                    "limit": limit,
                    "businessId": context.tenant_id,
                    "threadId": context.thread_id,
                }
            )
            second_products = [
                p for p in (second_res.get("products") or []) if p.get("id") not in {q["id"] for q in products}
            ]
            if second_products:
                merged: list[dict] = []
                for i in range(max(len(products), len(second_products))):
                    if i < len(products):
                        merged.append(products[i])
                    if i < len(second_products):
                        merged.append(second_products[i])
                products = merged[: max(limit, 4)]
            else:
                outfit_gap_note = f"\n（店内暂无{anchor}类现货，以上为装备部分）"

        candidate_product_ids = [p["id"] for p in products]

        # 上下文指代式对比(2026-09-14 用户实报):「最贵的 背包」→「最贵的和
        # 最便宜的对比」—— 对比句无品类词(极值词剥除+指代上一轮),检索必空。
        # 此处用上一轮检索词(lastSearchQuery)重提品类词,全量检索后取最贵 +
        # 最便宜两档对比展示;无上下文时保持诚实空。
        # S5 泛化(2026-09-15):「有没有中间价位的」同类 —— 无品类词指代上轮,
        # 词元(中间价位)检索必空;命中对比/价位指代 × 有上下文检索词即重检
        if not products and (self._COMPARE_RE.search(user_input) or self._PRICE_BAND_RE.search(user_input)):
            last_query = (existing_guide.get("lastSearchQuery") or "").strip()
            ctx_terms = [
                t for t in MallDomainService._extract_query_terms(last_query)
                if t not in ("对比", "不同", "差别", "区别")
            ][:3]
            if ctx_terms:
                # 走 search_products 完整链(词元展开/商户账本/降级链同源)
                ctx_query = " ".join(ctx_terms)
                full_res = await MallDomainService.search_products(
                    {"query": ctx_query, "limit": 50, "threadId": context.thread_id,
                     "businessId": context.tenant_id}
                )
                priced = sorted(
                    (p for p in (full_res.get("products") or []) if p.get("price") is not None),
                    key=lambda p: float(p["price"]),
                )
                # 中间价位(S5):≥3 档时去掉首尾极值,只留中位段
                if self._PRICE_BAND_RE.search(user_input) and len(priced) >= 3:
                    priced = priced[1:-1]
                if self._PRICE_BAND_RE.search(user_input) and priced:
                    items = priced[:3]
                    lines = "\n".join(
                        f"{i + 1}. 【{p['name']}】 ¥{p['price']} (现货 {p.get('stock')} 件)"
                        for i, p in enumerate(items)
                    )
                    return SkillResult(
                        skill_id=self.metadata["id"],
                        output=f"为您找到{('「' + ctx_terms[0] + '」') if ctx_terms else ''}中间价位的商品：\n\n{lines}",
                        guide_context={"lastSearchQuery": last_query},
                    )
                if len(priced) >= 2:
                    lo, hi = priced[0], priced[-1]
                    diff = float(hi["price"]) - float(lo["price"])

                    def _line(tag: str, item: dict) -> str:
                        return (
                            f"{tag}：【{item['name']}】 ¥{item['price']} (现货 {item.get('stock')} 件)\n"
                            f"   💡 {item.get('description') or ''}"
                        )

                    output = (
                        f"为您对比{('「' + ctx_terms[0] + '」') if ctx_terms else ''}最便宜与最贵的两款：\n\n"
                        f"{_line('💰 最便宜', lo)}\n\n"
                        f"{_line('💎 最贵', hi)}\n\n"
                        f"💰 价差：¥{diff:.0f}。{'价差主要来自容量/材质/配置档位，按用途选择即可' if diff > 0 else ''}"
                    )
                    return SkillResult(
                        skill_id=self.metadata["id"],
                        output=output,
                        guide_context={
                            "candidateProductIds": [lo["id"], hi["id"]],
                            "candidateProducts": [lo, hi],
                            "lastSearchQuery": last_query,
                            "extractedPreferences": extracted_prefs,
                            "clarificationRound": clarification_round,
                        },
                    )

        if not products:
            # 品类盘点引导(2026-09-12):诚实空不冷场 —— 告诉用户店里实际有什么,
            # 「卖得好」类模糊词落空时给可点选的真实方向,而非一句调整关键词。
            # 缺席反问查无(2026-09-27):以品类名词如实作答,严禁引用顾客反问原话。
            overview = await MallDomainService.get_shelf_overview()
            inventory_line = (
                "、".join(f"{o['category']}({o['spuCount']}款)" for o in overview) if overview else ""
            )
            if absence_topic:
                output = f"抱歉，店内暂时没有{absence_topic}在售。"
            else:
                output = f'抱歉，暂时未能找到完全符合"{user_input}"的现货商品。'
            output += (
                f"\n目前店内热卖品类：{inventory_line}，欢迎换个叫法或从这些品类挑挑看！"
                if inventory_line
                else "建议您可以调整预算或关键词再试一次！"
            )
            return SkillResult(skill_id=self.metadata["id"], output=output)

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

        # 💰 合计与预算结论(2026-09-27 实弹事故):此前没有任何一层算过合计,
        # finish LLM 却宣称「总价不超过2000元」(实为 329+899+1299=2527)。
        # 合计在此确定性算出并如实给结论,finish 终稿只许转述不许编。
        total_line = ""
        if len(products) >= 2:
            total = sum(float(p.get("price") or 0) for p in products)
            total_line = f"\n\n💰 以上 {len(products)} 件合计 ¥{total:.0f}"
            if max_price is not None:
                total_line += (
                    f"，在您 ¥{max_price} 预算内"
                    if total <= max_price
                    else f"，已超出您 ¥{max_price} 预算，可去掉一两件或调整预算再试"
                )

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
            "lastSearchQuery": absence_topic or user_input,
        }
        return SkillResult(
            skill_id=self.metadata["id"],
            output=output,
            cards=cards,
            guide_context=guide_context,
        )

    @staticmethod
    def _format_candidate(p: dict, idx: int) -> str:
        text = f"{idx + 1}. 【{p['name']}】 ¥{p.get('price')} (现货 {p.get('stock')} 件)\n   💡 {p.get('description')}"
        if p.get("specs"):
            spec_str = " | ".join(f"{k}:{v}" for k, v in p["specs"].items())
            text += f"\n   📐 特点: {spec_str}"
        return text
