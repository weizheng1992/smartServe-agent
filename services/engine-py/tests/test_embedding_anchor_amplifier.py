"""判定 3 退款放大器专册(2026-10-17 视觉加固 ④,embedding_anchor._damage_lights_refund)。

旧口径 ``bool(damage_assessment)``:任何非空评级(含 negligible)都点亮退款
关键词,判定 3 随即给 ``max(score_refund, 0.95)`` 的终局 refund 意图 —— 完好图
被幻觉/注入污染一次评级就强推退款终端,是单点放大器。收敛为 minor/severe 才
点亮;negligible 交回文本词表与 Step 3 LLM 精判。

纯函数专测;minor/severe 点亮的端到端时序(「坏了」× severe 回放)由
test_vision_order_consumption.py 钉死,此处不重复。
"""

from __future__ import annotations

from engine_py.triage.stages.embedding_anchor import _damage_lights_refund


def test_minor_and_severe_light_refund():
    assert _damage_lights_refund({"damageLevel": "minor"}) is True
    assert _damage_lights_refund({"damageLevel": "severe"}) is True


def test_negligible_no_longer_amplifies():
    """完好图评级不得点亮退款关键词 —— 旧口径的强推退款终端漏洞。"""
    assert _damage_lights_refund({"damageLevel": "negligible"}) is False


def test_none_and_empty_and_dirty_do_not_light():
    assert _damage_lights_refund(None) is False
    assert _damage_lights_refund({}) is False
    assert _damage_lights_refund({"damageLevel": "bogus"}) is False  # 脏数据同 negligible 口径
