"""L0 词林入口闸与趋势仲裁回归(2026-10-26/27 慢性缺口收口 + 2026-10-28 终审增补)。

- 关系问句闸:跨指标「关系/关联」一律 unsupported(闭集诚实律,严禁单指标
  synonym 半吸 —— 「坏账和退款的关系」曾答成 refund_rate);graph.ask 另有
  同款图级闸(注入闸同位),本册钉 L0 面
- 完整时间窗优先于趋势:「上个月销量」曾被 volume_trend 的 synonym「月销量」
  子串假命中(上个·月销量·长词优先),完整窗问的是该窗的量不是随时间的线
- 终审增补:日粒度语感词(每日/每天)护住闭窗×日粒度;orders 家族不参与榜单
  降级(top-N 语义无承接);月粒度豁免(last_months)钉死
"""

from __future__ import annotations

import pytest

from engine_py.analytics.engine import StructuredQueryIntent, UnsupportedQuery
from engine_py.analytics.l0_lexicon import resolve_question


def test_relation_question_gate_unsupported():
    """关系/关联问句:入口响亮拒绝(评测集 6 例同期望,含两晚慢性缺口)。

    注:「物流时效和评价的关系」「客户投诉和退货的关联」两例去掉闸词后本就
    闭集 miss(UnsupportedQuery 照抛),判别力在「坏账和退款的关系」(曾命中
    refund_rate)与「复购率和差评率的相关性」(可命中 repeat_purchase_rate)。
    """
    for q in (
        "坏账和退款的关系",
        "物流时效和评价的关系",
        "客户投诉和退货的关联",
        "复购率和差评率的相关性",
    ):
        with pytest.raises(UnsupportedQuery):
            resolve_question(q)


def test_last_month_volume_not_hijacked_by_trend():
    """慢性缺口主例:「上个月销量」= last_month 闭窗的总量,不是折线。"""
    intent = resolve_question("上个月销量")
    assert isinstance(intent, StructuredQueryIntent)
    assert intent.metric == "volume"
    assert intent.time_window == {"kind": "last_month"}


def test_bare_monthly_volume_still_trend():
    """不回归:裸「月销量」无完整时间窗,月粒度语感本义即趋势。"""
    intent = resolve_question("月销量")
    assert isinstance(intent, StructuredQueryIntent)
    assert intent.metric == "volume_trend"


def test_meiyue_volume_last_months_exemption_pinned():
    """月粒度豁免分支钉死(终审:载荷最重分支此前零覆盖):「每月销量」的
    last_months 窗(n 缺省 6)是趋势降级的唯一豁免 kind —— 豁免被误删时
    本例降级成 volume 即红。"""
    intent = resolve_question("每月销量")
    assert isinstance(intent, StructuredQueryIntent)
    assert intent.metric == "volume_trend"
    assert intent.time_window == {"kind": "last_months", "n": 6}


def test_daily_granularity_word_beats_window_arbitration():
    """终审增补:闭窗 × 日粒度语感 —— 「上个月每日销售额」问的是每日折线;
    日粒度词漏收白名单时曾被降级成 gmv(spu_rank 商品榜),序列粒度整层蒸发。"""
    intent = resolve_question("上个月每日销售额")
    assert isinstance(intent, StructuredQueryIntent)
    assert intent.metric == "gmv_trend"


def test_orders_trend_rank_words_not_downgraded():
    """终审增补:orders 家族不参与榜单降级 —— order_count 落点 total_single
    单值,top-N 语义无承接,「每日订单 top10」保持趋势(旧行为)。"""
    intent = resolve_question("每日订单 top10")
    assert isinstance(intent, StructuredQueryIntent)
    assert intent.metric == "orders_trend"
    assert intent.limit == 10


def test_explicit_trend_word_beats_window_arbitration():
    """不回归:显式趋势词(走势)在场时,完整窗不降级。"""
    intent = resolve_question("上个月销量走势")
    assert isinstance(intent, StructuredQueryIntent)
    assert intent.metric == "volume_trend"


def test_repeat_purchase_rank_registered():
    """复购率入注册表(5319e6b8)后,期望随口径翻转(原 expect_unsupported 已过时)。

    注(2026-10-28 终审):repeat_purchase_rate compile shape=total_single ——
    rank 语感的诚实答形(客户维度嵌套榜)依赖 T1 组合路(reason_reroute);
    AI_T1_COMPOSE=off 部署下 T0 出全店单值属系统性形状缺口,与本分类断言
    无关(评测集 13 条同型既有用例同口径),立案见 eval-gap 21 号票。
    """
    intent = resolve_question("复购率最高的客户有哪些")
    assert isinstance(intent, StructuredQueryIntent)
    assert intent.metric == "repeat_purchase_rate"


def test_rank_words_single_value_caliber_annotation():
    """21 号票裁决 B·注记的 graph 缝钉死:rank 语感 × 单值形指标 → 结果卡
    caliber 追加诚实口径注记(严禁静默半答);纯单值问句与榜单形指标不扰。"""
    from types import SimpleNamespace

    from engine_py.analytics.graph import _result_frame

    intent = SimpleNamespace(metric="repeat_purchase_rate", chart_hint=None)
    result = SimpleNamespace(metric="repeat_purchase_rate", unit="%", caliber="有效成交口径", rows=[], chart=None)
    assert "不支持按维度排行" in _result_frame("复购率最高的客户有哪些", result, intent)["caliber"]
    assert "不支持按维度排行" not in _result_frame("复购率是多少", result, intent)["caliber"]

    intent_gmv = SimpleNamespace(metric="gmv", chart_hint=None)
    result_gmv = SimpleNamespace(metric="gmv", unit="元", caliber="有效订单聚合", rows=[], chart=None)
    assert "不支持按维度排行" not in _result_frame("销售额最高的商品有哪些", result_gmv, intent_gmv)["caliber"]
