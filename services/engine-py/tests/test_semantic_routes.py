"""语义意图路由回归(P1 影子期):配置完整性 / 打分路由 / 模式开关。

影子期纪律:路由结果只产 proposals 不接管路由 —— 接线回归由
embedding_anchor 影子提议捕获(intent_logs.candidates 出现
layer=semantic_router)与巡检双指标兜底;本文件钉配置与打分纯逻辑。
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from engine_py.triage.intent_registry import INTENT_REGISTRY
from engine_py.triage.semantic_routes import (
    SEMANTIC_ROUTES,
    SemanticIntentRouter,
    get_semantic_router_mode,
    route_best_intent,
    validate_routes,
)


class TestRouteConfig:
    def test_all_routes_registered_in_intent_registry(self):
        problems = validate_routes()
        assert problems == [], f"路由配置完整性问题: {problems}"

    def test_routes_cover_core_shopping_intents(self):
        """核心购物档位必须在路由覆盖内(优惠荐品/导购是 P1 的立项动机)。"""
        for intent in ("promotion_query", "shopping_guide", "metric_query", "cart_manage"):
            assert intent in SEMANTIC_ROUTES

    def test_fallback_intents_excluded(self):
        """兜底类档位(general_query/out_of_scope/chat)路由到它们没有意义。"""
        for intent in ("general_query", "out_of_scope", "chat", "chitchat"):
            assert intent not in SEMANTIC_ROUTES

    def test_registry_parity_for_all_routes(self):
        for intent in SEMANTIC_ROUTES:
            assert intent in INTENT_REGISTRY, f"{intent} 未登记意图注册表"


class TestSemanticRouterScoring:
    @pytest.fixture(autouse=True)
    def _reset_vectors(self):
        """类级向量缓存是跨测试单例:每用例重置,防串扰。"""
        SemanticIntentRouter._route_vectors = None
        yield
        SemanticIntentRouter._route_vectors = None

    @staticmethod
    def _set_synthetic_vectors():
        """四轴正交合成向量:每意图沿自己的轴布两个锚点,命中判据纯几何。"""
        SemanticIntentRouter._route_vectors = {
            "promotion_query": [[1.0, 0.0, 0.0, 0.0], [0.96, 0.0, 0.0, 0.0]],
            "shopping_guide": [[0.0, 1.0, 0.0, 0.0], [0.0, 0.96, 0.0, 0.0]],
            "metric_query": [[0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.96, 0.0]],
        }

    def test_routes_to_best_intent_above_threshold(self):
        self._set_synthetic_vectors()
        hit = asyncio.run(SemanticIntentRouter.route_best([1.0, 0.0, 0.0, 0.0]))
        assert hit is not None and hit[0] == "promotion_query" and hit[1] == pytest.approx(1.0)

    def test_returns_none_below_all_thresholds(self):
        self._set_synthetic_vectors()
        hit = asyncio.run(SemanticIntentRouter.route_best([0.0, 0.0, 0.0, 1.0]))
        assert hit is None

    def test_sync_wrapper_none_when_vectors_cold(self):
        """向量未预热时同步封装诚实返回 None(影子接线失败让位,不炸主链)。"""
        SemanticIntentRouter._route_vectors = None
        assert route_best_intent([1.0, 0.0, 0.0, 0.0]) is None


class TestRouterMode:
    def test_default_mode_is_shadow(self, monkeypatch):
        monkeypatch.delenv("SEMANTIC_ROUTER_MODE", raising=False)
        assert get_semantic_router_mode() == "shadow"

    def test_mode_env_override(self, monkeypatch):
        monkeypatch.setenv("SEMANTIC_ROUTER_MODE", "off")
        assert get_semantic_router_mode() == "off"
        monkeypatch.setenv("SEMANTIC_ROUTER_MODE", "takeover")
        assert get_semantic_router_mode() == "takeover"
        monkeypatch.setenv("SEMANTIC_ROUTER_MODE", " nonsense ")
        assert get_semantic_router_mode() == "shadow", "非法值回落 shadow"

    def test_stage_module_imports_with_router(self):
        """embedding_anchor 影子接线不得破坏阶段模块导入。"""
        module = importlib.import_module(
            "engine_py.triage.stages.embedding_anchor"
        )
        assert hasattr(module, "judge")
