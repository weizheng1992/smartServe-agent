"""回归:经营口径排行规则前置(ADR-0003)—— 利润×排行共现直通 metric_query。

实弹三连拒:「按净毛利润最高的热销商品排行」被 LLM 分类层判成后台经营
数据拒答。规则前置确定性放行,只对利润词与排行词共现触发,严禁误伤
普通售后/订单咨询。
"""

from engine_py.triage.intent_triage_engine import is_profit_ranking_query


def test_profit_ranking_phrases_hit() -> None:
    for text in (
        "按净毛利润最高的热销商品排行 Top 5",
        "按毛利率最高查询热销商品排行",
        "查一下净毛利润商品排行",
        "利润最高的商品排名",
        "按利润排一下前5款商品",
    ):
        assert is_profit_ranking_query(text), text


def test_non_ranking_or_non_profit_do_not_hit() -> None:
    for text in (
        "我想申请退款",                    # 利润词都没有
        "有什么热销商品",                  # 排行语义但无利润词(走导购)
        "这个商品有没有毛领",              # 「毛」字但无利润词与排行词
        "订单什么时候发货",
        None,
    ):
        assert not is_profit_ranking_query(text), text
