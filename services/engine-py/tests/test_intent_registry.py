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
        # 16 档:2026-09-12 多意图 address_manage(规则层产出)之后,
        # 2026-09-18 优惠闭环新增 promotion_query(规则层产出,词表单一事实源)
        assert len(INTENT_REGISTRY) == 16

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
        # 可终局的档位(active/latent)必有产出层:分类器类目 prompt、规则层
        # INTENT_DETECTION_RULES,或 triage 专属检测器(intermediate/candidate
        # 例外:chat 是闸门中间信号,out_of_scope 只作候选)。
        # metric_query 即规则层产出、无类目;address_manage 产出层是
        # intent_triage_engine.detect_address_manage(判定 1.6 + Step3 注入器)。
        from engine_py.triage.intent_triage_engine import detect_address_manage

        terminal = set(reg.terminal_intents())
        prompt_covered = set(reg.prompt_category_intents())
        rule_covered = {r.intent for r in slot_extractor.INTENT_DETECTION_RULES}
        detector_covered = {reg.AgentIntentType.ADDRESS_MANAGE}
        assert detect_address_manage("看看我的收货地址") is not None, "检测器生产层失活"
        orphans = terminal - (prompt_covered | rule_covered | detector_covered)
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


class TestWordlistSingleSource:
    """词表单一事实源契约(admin-readiness 候选②):判定词表只许住
    intent_registry,消费方(engine/Stage)引用而非各自 re.compile。
    历史漏洞:订单词「查单/运单/面单」曾三处各写一半。"""

    def test_order_keyword_family_covered_by_slot_query_rule(self):
        """订单词族每一词的字面量都必须出现在 slot_extractor 模块源码的规则
        pattern 里 —— 「查单/运单/面单」曾只在 engine 侧有,embedding 分支与
        槽位层判定分叉。扫源码而非 import(规则在类内声明,无模块级导出)。"""
        import inspect

        from engine_py.triage import slot_extractor
        from engine_py.triage.intent_registry import ORDER_KEYWORD_FAMILY

        slot_source = inspect.getsource(slot_extractor)
        uncovered = [w for w in ORDER_KEYWORD_FAMILY if w not in slot_source]
        assert not uncovered, f"订单词族未进 slot 规则源码: {uncovered}"

    def test_refund_keywords_superset_of_verb_family(self):
        """REFUND_KEYWORDS = VERB 族 + 破损词:超集关系钉死,破损词不得混入
        slot 退款规则(「坏了」不是退款动词)。"""
        from engine_py.triage.intent_registry import REFUND_KEYWORDS_RE, REFUND_VERB_RE

        for verb in ("退款", "退了", "给我退", "申请退款"):
            assert REFUND_KEYWORDS_RE.search(verb)
        for damage in ("破损", "坏了", "碎了", "瑕疵"):
            assert REFUND_KEYWORDS_RE.search(damage)
        # 动词族本体必然是子集
        assert REFUND_VERB_RE.pattern in REFUND_KEYWORDS_RE.pattern

    def test_veto_re_equals_verb_family_plus_exchange(self):
        """资金否决 = VERB 族 + 换货(换货刻意不入族,防击穿咨询闸)。"""
        from engine_py.triage.intent_registry import MONEY_ACTION_VETO_RE, REFUND_VERB_RE

        assert "换货" in MONEY_ACTION_VETO_RE.pattern
        assert REFUND_VERB_RE.pattern in MONEY_ACTION_VETO_RE.pattern
        assert not REFUND_VERB_RE.search("换货")

    def test_operational_action_family_covers_core_ops(self):
        """重复拦截豁免词族必须覆盖核心操作词 —— 漏词会重放上一条 AI 答复。"""
        from engine_py.triage.intent_registry import OPERATIONAL_ACTION_RE

        for word in ("退款", "订单", "购物车", "推荐", "查询"):
            assert OPERATIONAL_ACTION_RE.search(word), word

    def test_unsanitized_tags_cover_all_tenant_markers(self):
        """未消毒标签正则覆盖全部已知租户标记前缀。"""
        from engine_py.triage.intent_registry import UNSANITIZED_TAGS_RE

        for tag in ("[ECOMMERCE]", "[NIKE]", "[ADIDAS]"):
            assert UNSANITIZED_TAGS_RE.search(tag)
