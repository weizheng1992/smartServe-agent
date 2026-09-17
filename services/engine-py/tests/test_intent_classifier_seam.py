"""缝①IntentScorer(wayfinder 11-D1;训练脚手架三缝之意图分类头)。

契约:锚点打分段抽为可替换接口,工厂 get_intent_classifier() 提供;
默认实现 = 现状锚点余弦打分(行为零变化,现有 triage 测试守门)。
训练产物训练完后以新 adapter 实现同接口接入,回滚 = 配置回退。
"""

from __future__ import annotations

import math

import pytest

from engine_py.llm.chat import get_intent_classifier
from engine_py.triage.intent_classifier import AnchorIntentClassifier, IntentScoreResult


class TestFactoryContract:
    def test_factory_returns_default_implementation(self):
        scorer = get_intent_classifier()
        assert isinstance(scorer, AnchorIntentClassifier), "默认实现必须是锚点打分(行为零变化红线)"

    def test_overrides_env_switches_implementation(self, monkeypatch):
        from engine_py.llm import chat

        monkeypatch.delenv("AI_INTENT_CLASSIFIER", raising=False)
        chat.get_intent_classifier.cache_clear()
        assert isinstance(chat.get_intent_classifier(), AnchorIntentClassifier)
        monkeypatch.setenv("AI_INTENT_CLASSIFIER", "custom")
        chat.get_intent_classifier.cache_clear()
        with pytest.raises(NotImplementedError):
            chat.get_intent_classifier()
        chat.get_intent_classifier.cache_clear()

    def test_factory_is_cached(self):
        assert get_intent_classifier() is get_intent_classifier()


class TestAnchorDefaultBehaviour:
    """默认实现的打分语义与现状锚点层逐位一致(零行为变化)。"""

    def test_score_pure_vectors(self):
        scorer = AnchorIntentClassifier()
        result = scorer.score(
            user_vector=[1.0, 0.0, 0.0],
            anchor_vectors={
                "order_status": [[1.0, 0.0, 0.0]],
                "refund": [[0.0, 1.0, 0.0]],
                "out_of_scope": [[0.0, 0.0, 1.0]],
            },
        )
        assert isinstance(result, IntentScoreResult)
        assert result.order_status == pytest.approx(1.0)
        assert result.refund == pytest.approx(0.0)
        assert result.out_of_scope == pytest.approx(0.0)

    def test_score_takes_max_over_anchor_set(self):
        scorer = AnchorIntentClassifier()
        result = scorer.score(
            user_vector=[1.0, 0.0],
            anchor_vectors={"order_status": [[0.6, 0.8], [1.0, 0.0]], "refund": [[0.0, 1.0]], "out_of_scope": [[-1.0, 0.0]]},
        )
        assert result.order_status == pytest.approx(1.0)  # max(0.6, 1.0)
        assert result.refund == pytest.approx(0.0)
        assert result.out_of_scope == pytest.approx(-1.0)

    def test_score_empty_anchor_group_is_zero(self):
        scorer = AnchorIntentClassifier()
        result = scorer.score(user_vector=[1.0], anchor_vectors={"order_status": [], "refund": [[1.0]], "out_of_scope": []})
        assert result.order_status == 0.0
        assert result.refund == pytest.approx(1.0)
        assert result.out_of_scope == 0.0

    def test_zero_vector_no_nan(self):
        scorer = AnchorIntentClassifier()
        result = scorer.score(
            user_vector=[0.0, 0.0],
            anchor_vectors={"order_status": [[0.0, 0.0]], "refund": [[1.0, 0.0]], "out_of_scope": [[0.0, 0.0]]},
        )
        for value in (result.order_status, result.refund, result.out_of_scope):
            assert not math.isnan(value)

    def test_result_is_immutable_dataclass(self):
        result = IntentScoreResult(order_status=0.5, refund=0.4, out_of_scope=0.1)
        with pytest.raises(AttributeError):  # frozen dataclass 拒绝改写
            result.order_status = 0.9  # type: ignore[misc]
