"""resolve_domain_role 注册表派生 parity(triage-review-remediation 工单04,2026-09-11)。

domain_role 进 intent_registry(意图元数据单一事实源),resolve_domain_role
档位判定只查表 —— 本套钉死两轴对齐与文本线索优先级:

1. 注册表 14 档位逐一 parity:resolve_domain_role([档位]) == spec.domain_role;
2. 未登记档位回退 chitchat;无 type 时取首元素;
3. 文本侧线索(购物车/导购措辞)优先于意图档位 —— 措辞含加购动词时即使
   档位是 chat/refund 也回 cart 域(文本维度非意图维度,旧判定次序保持)。
"""

from __future__ import annotations

import pytest

from engine_py.triage.intent_registry import INTENT_REGISTRY
from engine_py.triage.intent_triage_engine import resolve_domain_role


@pytest.mark.parametrize("intent", sorted(INTENT_REGISTRY))
def test_registry_parity_per_intent(intent: str):
    """档位轴:注册表每档 domain_role 与 resolve_domain_role 判定一一对应。"""
    spec = INTENT_REGISTRY[intent]
    assert resolve_domain_role([{"intent": intent, "type": "primary"}]) == spec.domain_role


def test_registry_parity_full_map():
    """快照轴:全量映射钉死,防止未来改表时静默漂移。"""
    resolved = {
        intent: resolve_domain_role([{"intent": intent, "type": "primary"}])
        for intent in INTENT_REGISTRY
    }
    assert resolved == {
        "cart_manage": "cart",
        "shopping_guide": "shopping_guide",
        "order_query": "order_service",
        "order_status": "order_service",
        "order_modify_address": "order_service",
        "address_manage": "shopping_guide",
        "order_cancel": "order_service",
        "order_return": "order_service",
        "refund": "order_service",
        "human_escalation": "order_service",
        "metric_query": "order_service",
        "chat": "chitchat",
        "general_query": "chitchat",
        "consult": "chitchat",
        "out_of_scope": "chitchat",
    }


def test_unknown_intent_falls_back_chitchat():
    assert resolve_domain_role([{"intent": "nonexistent_intent", "type": "primary"}]) == "chitchat"


def test_no_type_field_falls_back_to_first():
    assert resolve_domain_role([{"intent": "refund"}]) == "order_service"


@pytest.mark.parametrize(
    ("intent", "text", "expected"),
    [
        # 文本线索 × 弱意图档位:措辞维度接管
        ("chat", "帮我把这个加购", "cart"),
        ("chat", "有没有推荐的款", "shopping_guide"),
        # 文本线索优先于意图档位:refund 档位 × 导购措辞 → 导购域
        ("refund", "有没有推荐的款", "shopping_guide"),
        # 同文本含两类线索:购物车措辞先判(次序与旧实现一致)
        ("chat", "改成 2 件再推荐一下", "cart"),
        # 无文本线索:档位轴生效
        ("chat", "嗯嗯", "chitchat"),
    ],
)
def test_text_hint_precedence(intent: str, text: str, expected: str):
    assert resolve_domain_role([{"intent": intent, "type": "primary"}], text) == expected


def test_consult_side_intents_single_source():
    """咨询侧集合单一来源:badcase 冲突检测与 Step3 降级共用注册表口径,
    成员与历史集合逐字一致。"""
    from engine_py.badcase import intent_signals
    from engine_py.triage.intent_registry import CONSULT_SIDE_INTENTS

    assert set(CONSULT_SIDE_INTENTS) == {"consult", "general_query", "out_of_scope", "chat", "chitchat"}
    assert intent_signals._CONSULT_SIDE_INTENTS is CONSULT_SIDE_INTENTS


if __name__ == "__main__":
    pytest.main([__file__])
