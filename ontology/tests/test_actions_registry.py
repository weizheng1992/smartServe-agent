"""动作面迁移守卫 + 语义断言(ADR-0015 批一)。

迁移守卫:派生四词表与 gateway approval_actions.py:36-43 现行字面量逐成员
相等 —— 批一C 把 gateway 改为派生再出口后,本册继续钉「本体声明 ↔ 生成物 ↔
历史字面量」三方一致;任何一侧漂移红灯。
"""

from __future__ import annotations

from ontology import (
    ACTION_SPECS,
    CORE,
    CUSTOMER_ACTIONS,
    DEFAULT_REFUND_AUTO_APPROVAL_LIMIT,
    ENGINE_HANDLED_ACTIONS,
    OPERATOR_ACTIONS,
    SPI_ACTIONS,
    STAFF_REVIEW_ACTIONS,
    TS_GHOST_ACTIONS,
)

# gateway approval_actions.py 现行字面量(2026-10-19 冻结口径)
FROZEN_CUSTOMER = frozenset({"approve", "reject", "cancel", "start_human_takeover"})
FROZEN_OPERATOR = frozenset({"human_message", "human_finish", "release_takeover"})
FROZEN_STAFF_REVIEW = frozenset({"approve", "reject"})
FROZEN_SPI = FROZEN_CUSTOMER | FROZEN_OPERATOR | frozenset({"human_reply"})


def test_derived_faces_match_frozen_literals() -> None:
    assert CUSTOMER_ACTIONS == FROZEN_CUSTOMER
    assert OPERATOR_ACTIONS == FROZEN_OPERATOR
    assert STAFF_REVIEW_ACTIONS == FROZEN_STAFF_REVIEW
    assert SPI_ACTIONS == FROZEN_SPI


def test_engine_handled_set_is_all_actions() -> None:
    assert ENGINE_HANDLED_ACTIONS == frozenset(ACTION_SPECS)
    assert SPI_ACTIONS == ENGINE_HANDLED_ACTIONS   # 现行口径:三面曝光 ∪ = 引擎受理


def test_faces_closed_and_nonempty() -> None:
    face_keys = {item.key for item in CORE.faces}
    for name, spec in ACTION_SPECS.items():
        assert spec.faces, name
        assert set(spec.faces) <= face_keys, f"{name} 越面: {set(spec.faces) - face_keys}"


def test_ghosts_disjoint_from_handled() -> None:
    assert TS_GHOST_ACTIONS == frozenset({"reply"})
    assert not (TS_GHOST_ACTIONS & ENGINE_HANDLED_ACTIONS)


def test_refund_limit_default_is_50() -> None:
    """ADR-0015 决策 4:缺省统一 50(收紧方向);租户覆写通道不在此层。"""
    assert DEFAULT_REFUND_AUTO_APPROVAL_LIMIT == 50.0


def test_permission_format_when_present() -> None:
    """permission 锚非空时必须是 `域:动作` 形;真实性断言(存在性)在
    gateway 契约册(test_approval_action_registry)对拍 rbac 真实 perm 集。"""
    for name, spec in ACTION_SPECS.items():
        if spec.permission is not None:
            assert ":" in spec.permission and " " not in spec.permission, name
