"""导购检索编排(深 implementation):主检索 + 搭配族缺补脚 + 上下文指代
对比/价位带重检 + 诚实空货架盘点。

数据通路 = MallDomainService 统一检索链(词元展开/商户真账/降级链同源)——
域服务语义,不过 SPI 缝(SPI 形是第三方目录契约的防腐翻译,见
spi_client.search_products;两者角色不同而非漂移,2026-10-07 查证)。
"""

from __future__ import annotations

from ...tools_registry.mall_domain import MallDomainService
from ..contract import SkillResult
from . import resolver


async def search_with_outfit_fill(
    *,
    user_input: str,
    absence_topic: str | None,
    max_price: int | None,
    color_pref: str | None,
    limit: int,
    tenant_id: str,
    thread_id: str | None,
) -> tuple[list[dict], str]:
    """主检索 + 🧳 搭配族缺补脚(2026-09-27 实弹事故):输入含衣着锚词而首脚
    命中零衣着商品(「装备」凭品类列子串吃满 limit)→ 以裸锚词补一脚,两脚
    交错合并(装备×衣着交替,截断也保两族在场)。补脚仍空 → 如实标注店内无
    该族,严禁静默只推单族冒充「一套」。返回 (products, 缺族注记)。"""
    search_res = await MallDomainService.search_products(
        {
            "query": absence_topic or user_input,
            "maxPrice": max_price,
            "color": color_pref,
            "limit": limit,
            "businessId": tenant_id,
            "threadId": thread_id,
        }
    )
    products = search_res.get("products") or []

    outfit_gap_note = ""
    if (
        products
        and absence_topic is None
        and resolver.OUTFIT_RE.search(user_input)
        and resolver.CLOTHING_ANCHOR_RE.search(user_input)
        and not any(resolver.CLOTHING_ANCHOR_RE.search(str(p.get("name") or "")) for p in products)
    ):
        anchor = resolver.CLOTHING_ANCHOR_RE.search(user_input).group(0)
        second_res = await MallDomainService.search_products(
            {
                "query": anchor,
                "maxPrice": max_price,
                "color": color_pref,
                "limit": limit,
                "businessId": tenant_id,
                "threadId": thread_id,
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
    return products, outfit_gap_note


async def price_band_compare(
    *,
    user_input: str,
    existing_guide: dict,
    tenant_id: str,
    thread_id: str | None,
    extracted_prefs: dict | None = None,
    clarification_round: int = 0,
) -> SkillResult | None:
    """上下文指代式对比(2026-09-14 用户实报):「最贵的 背包」→「最贵的和
    最便宜的对比」—— 对比句无品类词(极值词剥除+指代上一轮),检索必空。
    用上一轮检索词(lastSearchQuery)重提品类词,全量检索后取最贵 + 最便宜
    两档对比展示;无上下文时返回 None(保持诚实空)。
    S5 泛化(2026-09-15):「有没有中间价位的」同类 —— ≥3 档时去掉首尾极值,
    只留中位段。"""
    if not (resolver.COMPARE_RE.search(user_input) or resolver.PRICE_BAND_RE.search(user_input)):
        return None
    last_query = (existing_guide.get("lastSearchQuery") or "").strip()
    # MallDomainService 私有分词面:词元展开单一实现,公开化牵动面大于收益,
    # 此处沿用(与 split 无关的既有触手,在案)
    ctx_terms = [
        t for t in MallDomainService._extract_query_terms(last_query)
        if t not in ("对比", "不同", "差别", "区别")
    ][:3]
    if not ctx_terms:
        return None
    # 走 search_products 完整链(词元展开/商户账本/降级链同源)
    full_res = await MallDomainService.search_products(
        {"query": " ".join(ctx_terms), "limit": 50, "threadId": thread_id, "businessId": tenant_id}
    )
    priced = sorted(
        (p for p in (full_res.get("products") or []) if p.get("price") is not None),
        key=lambda p: float(p["price"]),
    )
    # 中间价位(S5):≥3 档时去掉首尾极值,只留中位段
    if resolver.PRICE_BAND_RE.search(user_input) and len(priced) >= 3:
        priced = priced[1:-1]
    if resolver.PRICE_BAND_RE.search(user_input) and priced:
        items = priced[:3]
        lines = "\n".join(
            f"{i + 1}. 【{p['name']}】 ¥{p['price']} (现货 {p.get('stock')} 件)"
            for i, p in enumerate(items)
        )
        return SkillResult(
            skill_id="skill_shopping_guide",
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
            skill_id="skill_shopping_guide",
            output=output,
            guide_context={
                "candidateProductIds": [lo["id"], hi["id"]],
                "candidateProducts": [lo, hi],
                "lastSearchQuery": last_query,
                "extractedPreferences": extracted_prefs or {},
                "clarificationRound": clarification_round,
            },
        )
    return None


async def empty_shelf_output(*, absence_topic: str | None, user_input: str) -> str:
    """品类盘点引导(2026-09-12):诚实空不冷场 —— 告诉用户店里实际有什么,
    「卖得好」类模糊词落空时给可点选的真实方向,而非一句调整关键词。
    缺席反问查无(2026-09-27):以品类名词如实作答,严禁引用顾客反问原话。"""
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
    return output
