"""planner 深度规划 max_tokens 封顶(2026-09-09)。

glm-4.7 曾对「退货政策」类简单问题生成 5163 token(73.7s,见 llm_call_logs);
planner_llm() 以 bind(max_tokens=AI_PLANNER_MAX_TOKENS) 封顶,截断 JSON 落
planner 兜底单步计划。钉死两件事:
1. 封顶值来自 settings 且随 env 生效;
2. bind 仍包着 _ResilientChatOpenAI(熔断/遥测公共入口不丢失)。
"""

from __future__ import annotations

import pytest

from engine_py.config import settings
from engine_py.graph.nodes.planner import planner_llm
from engine_py.llm.chat import _ResilientChatOpenAI


def test_planner_llm_caps_max_tokens_from_settings():
    bound = planner_llm()
    assert bound.kwargs.get("max_tokens") == settings.planner_max_tokens
    assert settings.planner_max_tokens > 0


def test_planner_llm_keeps_resilient_entry():
    bound = planner_llm()
    assert isinstance(bound.bound, _ResilientChatOpenAI)  # 熔断/逐调用遥测挂点仍在


if __name__ == "__main__":
    pytest.main([__file__])
