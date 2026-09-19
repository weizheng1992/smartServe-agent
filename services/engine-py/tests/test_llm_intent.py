"""L3 LLM 意图层纯逻辑单测(不触网;ADR-0005)。

覆盖:围栏 JSON 解析、l3_enabled 开关、实体必填映射与注册表一致性、
系统提示词包含闭集目录。
"""

from __future__ import annotations

import pytest

from engine_py.analytics.llm_intent import (
    ENTITY_REQUIRED,
    LlmIntent,
    _parse_llm_json,
    _system_prompt,
    l3_enabled,
)
from engine_py.analytics.tools_registry_bridge import metric_semantic_registry


class TestParseLlmJson:
    def test_plain_json(self):
        assert _parse_llm_json('{"metric": "gmv"}') == {"metric": "gmv"}

    def test_markdown_fence_stripped(self, ):
        raw = "```json\n{\"metric\": \"gmv\", \"limit\": null}\n```"
        assert _parse_llm_json(raw)["metric"] == "gmv"

    def test_braces_extracted_from_prose(self):
        raw = '好的,解析结果如下:{"metric": "volume"} 请查收'
        assert _parse_llm_json(raw)["metric"] == "volume"

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            _parse_llm_json("抱歉我不知道")

    def test_model_validate_roundtrip(self):
        out = LlmIntent.model_validate(_parse_llm_json('```json\n{"metric": "gmv", "direction": "DESC"}\n```'))
        assert out.metric == "gmv" and out.limit is None


class TestL3Enabled:
    def test_default_on(self, monkeypatch):
        monkeypatch.delenv("AI_INTENT_L3", raising=False)
        assert l3_enabled() is True

    def test_off_by_env(self, monkeypatch):
        for value in ("off", "0", "false", "OFF"):
            monkeypatch.setenv("AI_INTENT_L3", value)
            assert l3_enabled() is False


class TestClosedSetConsistency:
    """实体必填映射的指标必须都在注册表闭集内(防漂移)。"""

    def test_entity_required_keys_registered(self):
        registry = metric_semantic_registry()
        assert set(ENTITY_REQUIRED) <= set(registry)
        assert all(kind in ("promotion", "customer", "spu") for kind in ENTITY_REQUIRED.values())

    def test_system_prompt_contains_closed_catalog(self):
        prompt = _system_prompt(None)
        for key in ("gmv", "promo_effect", "customer_orders"):
            assert key in prompt
        assert "闭集" in prompt
