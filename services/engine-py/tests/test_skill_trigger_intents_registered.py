"""技能 triggerIntents 对意图注册表的闭集契约(A5,2026-10-03)。

can_handle 是原样大小写敏感成员判断 —— 声明了注册表外/大小写不符的触发词
即**永不命中的死词**:主匹配路径名存实亡,技能实际全靠兜底正则开火
(2026-10-03 清理前普查:六技能七类死词 —— UPPER 变体 ×4、工具名
process_refund、product_query/mall_search/coupon_query/cart_add/cart_update/
modify_address)。本册钉死两层,防止死词回潮:

① 每个登记技能的每个触发词 ∈ REGISTERED_INTENTS(注册表闭集,大小写归一);
② 每个技能至少持一个活触发词(全死 = 技能永不经主路径命中)。
"""

from __future__ import annotations

import pytest

from engine_py.skills import SkillRegistry
from engine_py.triage.intent_registry import REGISTERED_INTENTS


def _skills():
    skills = SkillRegistry.get_all_skills()
    assert skills, "技能注册表为空(初始化断裂)"
    return skills


@pytest.mark.parametrize("skill", _skills(), ids=lambda s: s.metadata["id"])
def test_every_trigger_intent_is_registered(skill):
    triggers = skill.metadata.get("triggerIntents") or []
    assert triggers, f"{skill.metadata['id']} 未声明任何触发意图"
    dead = [t for t in triggers if str(t).strip().lower() not in REGISTERED_INTENTS]
    assert dead == [], f"{skill.metadata['id']} 声明了注册表外死词(永不命中): {dead}"


@pytest.mark.parametrize("skill", _skills(), ids=lambda s: s.metadata["id"])
def test_every_skill_has_one_live_trigger(skill):
    live = [
        t for t in (skill.metadata.get("triggerIntents") or [])
        if str(t).strip().lower() in REGISTERED_INTENTS
    ]
    assert live, f"{skill.metadata['id']} 全部触发词均为死词,技能永不经主匹配命中"


def test_trigger_words_are_lowercase_normalized():
    """UPPER 变体在大小写敏感成员判断下是死词(ORDER_RETURN ≠ order_return):
    声明面统一小写,本册让大小写漂移当场红。"""
    for skill in _skills():
        for t in skill.metadata.get("triggerIntents") or []:
            assert t == t.lower(), f"{skill.metadata['id']} 触发词含大写:{t!r}(永不命中)"


def test_registered_intents_closure_shape():
    """闭集自身形状:全小写蛇形、无空串。"""
    assert all(v == v.lower() and v for v in REGISTERED_INTENTS)
    assert {"refund", "order_return", "order_cancel", "shopping_guide"} <= REGISTERED_INTENTS
