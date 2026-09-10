"""意图注册表奇偶校验(intent-arbitration 04,2026-09-10)。

注册表是全部意图档位的单一事实来源:本套钉死它与四类消费方的对齐 ——
AgentIntentType 常量、结构化分类器 10 类目 prompt、单号正则三使用点、
同义对与生命周期语义。零标签变更:任何标签改动都会在此当场爆红。
"""

from __future__ import annotations

import re

from engine_py.graph.nodes import planner
from engine_py.graph.nodes import utils as node_utils
from engine_py.triage import intent_registry as reg
from engine_py.triage import slot_extractor
from engine_py.triage.intent_registry import (
    CATEGORY_GUIDELINES,
    EXPLICIT_ORDER_ID_RE,
    INTENT_REGISTRY,
    VISION_ORDER_ID_RE,
)
from engine_py.triage.structured_classifier import SYSTEM_PROMPT_TEMPLATE
from engine_py.vision import analyzer

# ---------------------------------------------------------------------------
# 1. 注册表 ↔ AgentIntentType 常量一一对应(零标签变更)
# ---------------------------------------------------------------------------

class TestRegistryAlignment:
    def test_registry_keys_equal_intent_type_values(self):
        type_values = {
            v for k, v in vars(reg.AgentIntentType).items() if not k.startswith("_")
        }
        assert set(INTENT_REGISTRY) == type_values
        assert len(INTENT_REGISTRY) == 14

    def test_slot_extractor_reexports_same_class(self):
        # 定义已迁 intent_registry,slot_extractor.AgentIntentType 是同一类对象
        assert slot_extractor.AgentIntentType is reg.AgentIntentType

    def test_spec_name_matches_key(self):
        for key, spec in INTENT_REGISTRY.items():
            assert spec.name == key

    def test_valid_lifecycle_values(self):
        valid = {"active", "latent", "intermediate", "candidate_only"}
        for spec in INTENT_REGISTRY.values():
            assert spec.lifecycle in valid, spec.name

    def test_active_intents_have_consumers(self):
        # active = 有终局消费方;没消费方的档位必须如实标 latent/intermediate/candidate_only
        for spec in INTENT_REGISTRY.values():
            if spec.lifecycle == "active":
                assert spec.consumers, f"{spec.name} active 但零消费方盘点"

    def test_synonyms_bidirectional(self):
        for spec in INTENT_REGISTRY.values():
            for syn in spec.synonyms:
                other = INTENT_REGISTRY[syn]
                assert spec.name in other.synonyms, (
                    f"同义对单向:{spec.name}→{syn} 无回指"
                )


# ---------------------------------------------------------------------------
# 2. 类目指南:prompt 与注册表同源
# ---------------------------------------------------------------------------

class TestCategoryGuidelines:
    def test_template_renders_guidelines(self):
        rendered = SYSTEM_PROMPT_TEMPLATE.format(
            category_guidelines=CATEGORY_GUIDELINES,
            exemplars_section="",
            recent_history="No previous history.",
            input="测试",
        )
        # 渲染产物包含全部 10 条类目行(逐字迁出,改一个字这里即红)
        for n in range(1, 11):
            assert re.search(rf"^{n}\. ", CATEGORY_GUIDELINES, re.MULTILINE)
        assert "consult" in rendered
        assert "{category_guidelines}" not in rendered

    def test_prompt_category_intents_covered_by_guidelines(self):
        # 每个声明了 prompt_category 的档位,其标签必出现在指南文本里
        for spec in INTENT_REGISTRY.values():
            if spec.prompt_category is not None:
                assert f'"{spec.name}"' in CATEGORY_GUIDELINES, spec.name

    def test_terminal_intents_have_a_producer_layer(self):
        # 可终局的档位(active/latent)必有产出层:分类器类目 prompt 或规则层
        # INTENT_DETECTION_RULES(intermediate/candidate 例外:chat 是闸门中间
        # 信号,out_of_scope 只作候选)。metric_query 即规则层产出、无类目。
        terminal = set(reg.terminal_intents())
        prompt_covered = set(reg.prompt_category_intents())
        rule_covered = {r.intent for r in slot_extractor.INTENT_DETECTION_RULES}
        orphans = terminal - (prompt_covered | rule_covered)
        assert not orphans, orphans


# ---------------------------------------------------------------------------
# 3. 单号正则三使用点收口(行为不变)
# ---------------------------------------------------------------------------

class TestOrderIdRegexConvergence:
    def test_planner_uses_registry_regex(self):
        assert planner._EXPLICIT_ORDER_ID_RE is EXPLICIT_ORDER_ID_RE

    def test_node_utils_alias_is_registry_regex(self):
        assert node_utils.ORDER_ID_UTIL_RE is EXPLICIT_ORDER_ID_RE

    def test_vision_analyzer_uses_registry_regex(self):
        assert analyzer._ORDER_RE is VISION_ORDER_ID_RE

    def test_explicit_regex_matches(self):
        assert EXPLICIT_ORDER_ID_RE.search("退款订单 ORD-98712") .group(0) == "ORD-98712"
        # 前缀复合单号((?:[A-Za-z0-9]+-)* 允许 SG-ORD-123 一类)
        assert EXPLICIT_ORDER_ID_RE.search("SG-ORD-123").group(0) == "SG-ORD-123"
        assert not EXPLICIT_ORDER_ID_RE.search("没有单号")

    def test_vision_regex_word_boundary(self):
        # 词边界更严:前缀复合单号的尾巴不带前缀整段
        assert VISION_ORDER_ID_RE.search("SG-ORD-123").group(0) == "ORD-123"
        assert not VISION_ORDER_ID_RE.search("没有单号")

    def test_slot_extractor_loose_regex_stays(self):
        # 宽松抽取器刻意不迁:还兜裸数字/无前缀单号,语义与严格匹配不同
        assert slot_extractor.ORDER_ID_RE is not EXPLICIT_ORDER_ID_RE
        assert slot_extractor.ORDER_ID_RE.search("单号 12345678") is not None


# ---------------------------------------------------------------------------
# 4. 同义对与已知缺口的现行行为(变更前钉住)
# ---------------------------------------------------------------------------

class TestKnownGaps:
    def test_order_query_status_synonym_pair(self):
        assert INTENT_REGISTRY["order_query"].synonyms == ("order_status",)
        assert INTENT_REGISTRY["order_status"].synonyms == ("order_query",)

    def test_refund_return_synonym_pair(self):
        assert INTENT_REGISTRY["refund"].synonyms == ("order_return",)
        assert INTENT_REGISTRY["order_return"].synonyms == ("refund",)

    def test_known_gap_order_cancel_documented(self):
        spec = INTENT_REGISTRY["order_cancel"]
        assert spec.lifecycle == "latent"
        assert spec.consumers == ()

    def test_out_of_scope_is_candidate_only(self):
        assert INTENT_REGISTRY["out_of_scope"].lifecycle == "candidate_only"

    def test_consult_consumed_only_in_triage(self):
        spec = INTENT_REGISTRY["consult"]
        assert spec.lifecycle == "active"
        assert all("triage" in c for c in spec.consumers)
