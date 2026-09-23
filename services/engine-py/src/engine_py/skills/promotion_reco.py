"""优惠荐品引擎(P1 从 PromotionQuerySkill 拆出,2026-09-23 code-review 12)。

职责收敛:荐品的问法解析(预算/价格诉求)、目录收集(一次拉活动集内存打分,
根除逐 SPU 查询 N+1)、排序渲染、多轮 refine(guide_context 跨轮排除已荐/
预算过滤)。券包问答与活动列表仍归 promotion_skill 本体 —— 拆分只挪增长
最快的荐品块。缺货商品不荐(HAVING SUM(stock)>0)。
"""

from __future__ import annotations

import re

from sqlalchemy import text

from ..analytics.promotion_engine import (
    best_discount_for_amount,
    fetch_active_promos,
)

# 多轮 refine(2026-09-23 实弹):「太贵了，来点便宜些优惠大的」曾被原样
# 复读全局榜 —— 价格诉求/预算/换一批措辞触发排除已荐与按价升序
_BUDGET_RE = re.compile(
    r"(?:(\d{2,5})\s*(?:元|块)?\s*(?:以内|以下))|(?:预算|不超过|最多)\s*(\d{2,5})\s*(?:元|块)?"
)
_CHEAPER_RE = re.compile(r"太贵|贵了|价格高|便宜|低一点|低一些")
_OTHERS_RE = re.compile(r"其他|别的|换一批|换几款|还有别的")

_CATALOG_SQL = (
    "SELECT p.spu_code, p.title, MIN(s.price) AS price, COALESCE(SUM(s.stock), 0) AS stock "
    "FROM merchant_spus p JOIN merchant_skus s ON s.spu_id = p.id "
    "WHERE p.status = 'ON_SALE' AND s.price IS NOT NULL "
    "GROUP BY p.spu_code, p.title HAVING COALESCE(SUM(s.stock), 0) > 0"
)


def parse_price_hint(question: str) -> tuple[float | None, bool]:
    """(预算上限|None, 是否价格诉求)。"""
    budget: float | None = None
    m = _BUDGET_RE.search(question)
    if m:
        budget = float(m.group(1) or m.group(2))
    return budget, bool(_CHEAPER_RE.search(question))


def is_deal_recommendation_ask(question: str, budget: float | None, cheaper: bool) -> bool:
    """荐品问法判定:荐品词面 / 预算 / 价格诉求任一即荐。"""
    if _RECOMMEND_RE().search(question) or budget is not None or cheaper:
        return True
    return False


def _RECOMMEND_RE() -> re.Pattern:
    from .promotion_skill import _RECOMMEND_RE  # 局部导入避免环

    return _RECOMMEND_RE


async def recommend_deals(
    conn, guide_context: dict, question: str
) -> tuple[str, list[str]]:
    """优惠荐品主入口:返回 (文案, 本轮已荐 spu_codes)。

    - 默认按立减额降序 Top 3(平局价升序,同力度优先便宜且确定可测);
    - 价格诉求(太贵/便宜些)→ 排除已荐商品并按价格升序荐剩余有活动力度者;
    - 「X 元以内/预算 X」按价格上限过滤、力度降序;
    - refine 后无货诚实告知并引导报预算,严禁把用户嫌贵的产品列回去;
    - 无活动诚实空;缺货商品不荐。"""

    budget: float | None = None
    budget_match = _BUDGET_RE.search(question)
    if budget_match:
        budget = float(budget_match.group(1) or budget_match.group(2))
    cheaper = bool(_CHEAPER_RE.search(question))
    refining = cheaper or bool(_OTHERS_RE.search(question)) or budget is not None
    last_shown = set((guide_context or {}).get("promotion_recommendation", {}).get("spuCodes") or [])

    products = (
        await conn.execute(text(_CATALOG_SQL))
    ).mappings().all()
    promos = await fetch_active_promos(conn)

    def _collect(exclude: set[str]) -> list[dict]:
        deals: list[dict] = []
        for row in products:
            spu_code = str(row["spu_code"])
            if spu_code in exclude:
                continue
            price = float(row["price"])
            if budget is not None and price > budget:
                continue
            best = best_discount_for_amount(promos, spu_code, price)
            if best and best["discount"] > 0:
                deals.append(
                    {
                        "spu_code": spu_code,
                        "title": row["title"],
                        "price": price,
                        "discount": best["discount"],
                        "name": best["name"],
                        "promo_price": round(price - best["discount"], 2),
                    }
                )
        return deals

    exclude = last_shown if refining else set()
    deals = _collect(exclude)
    refined_empty = refining and not deals
    if refined_empty:
        # 排除已荐后无货:诚实告知并引导报预算,严禁把用户嫌贵的产品列回去
        return (
            "更便宜且优惠力度大的商品暂时没有。可以告诉我预算（如「300以内」），"
            "或看看在售优惠活动～"
        ), []
    if not deals:
        return "当前没有进行中的商品优惠，暂时没有优惠推荐。", []

    if cheaper:
        deals.sort(key=lambda d: d["price"])
    else:
        # 立降额优先;平局按价升序(同力度优先便宜,且排序确定可测)
        deals.sort(key=lambda d: (-d["discount"], d["price"]))
    top = deals[:3]
    spu_codes = [d["spu_code"] for d in top]

    lines = ["🎁 优惠力度最大的商品："]
    for d in top:
        lines.append(
            f"• {d['title']} ¥{d['price']:.0f} → ¥{d['promo_price']:.0f}"
            f"（{d['name']}，立减 ¥{d['discount']:.0f}）"
        )
    lines.append("")
    lines.append("领券后可与活动叠加：活动先减，优惠券按余额抵扣。")
    return "\n".join(lines), spu_codes
