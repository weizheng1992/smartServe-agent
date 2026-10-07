"""导购结果卡与推荐语渲染(纯函数)。

诚实性(ADR-0002 数据条件禁令):商户货架无销量数据,推荐卡严禁「热销」
字样与编造分数(metricScore=99-idx*5 已拆)—— 只带真实字段(价格/现货/
品类)+ 推荐位次;rankingMetric=recommendation 让卡合成器识别为推荐卡而非
真排行(不触发统计口径消歧组)。
"""

from __future__ import annotations


def build_ranking_card(products: list[dict]) -> dict:
    """推荐位次卡:真实字段(价格/现货/品类)+ 推荐位次,零编造分数。"""
    return {
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


def format_candidate(p: dict, idx: int) -> str:
    text = f"{idx + 1}. 【{p['name']}】 ¥{p.get('price')} (现货 {p.get('stock')} 件)\n   💡 {p.get('description')}"
    if p.get("specs"):
        spec_str = " | ".join(f"{k}:{v}" for k, v in p["specs"].items())
        text += f"\n   📐 特点: {spec_str}"
    return text


def budget_total_line(products: list[dict], max_price: int | None) -> str:
    """💰 合计与预算结论(2026-09-27 实弹事故):此前没有任何一层算过合计,
    finish LLM 却宣称「总价不超过2000元」(实为 329+899+1299=2527)。
    合计在此确定性算出并如实给结论,finish 终稿只许转述不许编。"""
    if len(products) < 2:
        return ""
    total = sum(float(p.get("price") or 0) for p in products)
    total_line = f"\n\n💰 以上 {len(products)} 件合计 ¥{total:.0f}"
    if max_price is not None:
        total_line += (
            f"，在您 ¥{max_price} 预算内"
            if total <= max_price
            else f"，已超出您 ¥{max_price} 预算，可去掉一两件或调整预算再试"
        )
    return total_line
