"""排行卡合成契约:searchProducts 工具结果不得误装排行卡(2026-09-12 事故)。

事故链:planner 选 searchProducts 工具(非导购技能)→ subtask.result.output
= {"total": N, "products": [商户货架检索形条目]} → 卡合成器旧判定
「products 非空即排行卡」误装 → 前端 ProductRankingCard 读缺失的
totalGmv 抛 toLocaleString TypeError,聊天控制台白屏。
"""

from engine_py.cards.card_synthesizer import CardSynthesizer

# 商户货架检索形条目(mall_domain._fetch_merchant_catalog 出参,无排行字段)
_SEARCH_SHAPED_OUTPUT = {
    "total": 1,
    "query": "背包",
    "products": [
        {
            "id": "BAG-001",
            "name": "户外徒步背包 45L",
            "price": 829.0,
            "stock": 12,
            "description": "大容量防泼水",
            "category": "背包收纳",
            "specs": {"容量": "45L"},
            "imageUrl": None,
        }
    ],
}


def _plan_with_output(output: dict, step_id: str = "search_products_1") -> dict:
    return {
        "subtasks": [
            {
                "id": step_id,
                "description": "为用户搜索背包商品",
                "status": "completed",
                "result": {"toolExecuted": "searchProducts", "output": output},
            }
        ]
    }


def test_search_tool_result_never_becomes_ranking_card() -> None:
    """检索结果不是销售排行:不得凭 products 非空合成排行卡。"""
    cards = CardSynthesizer.synthesize_cards({"taskPlan": _plan_with_output(_SEARCH_SHAPED_OUTPUT)})
    assert not [c for c in cards if c.get("type") == "product_ranking"]


def test_real_ranking_result_still_synthesizes_ranking_card() -> None:
    """真排行结果(queryProductRanking 形,带 rankingMetric)照常合成。"""
    ranking_output = {
        "success": True,
        "rankingMetric": "gmv",
        "metricLabel": "总销售额 (GMV)",
        "metricUnit": "元",
        "itemCount": 1,
        "summary": "已为您完成排行的排行检索。",
        "products": [
            {
                "rank": 1,
                "productId": "prod-1",
                "name": "Nike Air Zoom Pegasus 41",
                "category": "running_shoes",
                "price": 899.0,
                "costPrice": 539.4,
                "stock": 58,
                "totalVolume": 10,
                "totalGmv": 8990.0,
                "grossProfit": 3596.0,
                "marginRate": "40.0%",
                "metricScore": 8990.0,
                "metricDisplay": "8,990 元",
            }
        ],
    }
    cards = CardSynthesizer.synthesize_cards({"taskPlan": _plan_with_output(ranking_output, "rank_products_1")})
    ranking_cards = [c for c in cards if c.get("type") == "product_ranking"]
    assert len(ranking_cards) == 1
    assert ranking_cards[0]["data"]["metricLabel"] == "总销售额 (GMV)"
    assert ranking_cards[0]["data"]["products"][0]["totalGmv"] == 8990.0
