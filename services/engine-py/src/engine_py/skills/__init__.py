"""技能注册中心 — 镜像 skills/skillRegistry.ts + index.ts。"""

from __future__ import annotations

from .base_skill import BaseSkill
from .cart_manage_skill import CartManageSkill
from .guide_skills import ProductInquirySkill, ShoppingGuideSkill
from .order_skills import OrderAddressModificationSkill, OrderRefundSkill


class SkillRegistry:
    _skills: dict[str, BaseSkill] = {}

    @classmethod
    def _ensure_initialized(cls) -> None:
        if not cls._skills:
            for skill in (
                OrderAddressModificationSkill(),
                OrderRefundSkill(),
                ProductInquirySkill(),
                ShoppingGuideSkill(),
                CartManageSkill(),
            ):
                cls.register(skill)

    @classmethod
    def register(cls, skill: BaseSkill) -> None:
        cls._skills[skill.metadata["id"]] = skill

    @classmethod
    def get_skill(cls, skill_id: str) -> BaseSkill | None:
        cls._ensure_initialized()
        return cls._skills.get(skill_id)

    @classmethod
    def get_all_skills(cls) -> list[BaseSkill]:
        cls._ensure_initialized()
        return list(cls._skills.values())

    @classmethod
    def find_matching_skill(cls, context: dict) -> BaseSkill | None:
        cls._ensure_initialized()
        for skill in cls._skills.values():
            if skill.can_handle(context):
                return skill
        return None


def is_action_query(input_text: str, tenant_id: str = "") -> bool:
    """业务动作嗅探:任一已注册技能声明可处理该输入则返回 True。

    语义缓存只服务纯寒暄/FAQ 回复;"动作形"输入(加购/退款/改址等)必须走真实
    执行管道 —— finish 节点据此拒绝回填缓存、triage Step 2 据此拒绝命中缓存,
    防止技能层异常降级为 general_query 后,LLM 幻觉的"已成功 XX"回复经缓存
    投毒扩散(2026-09-04 幻觉加购 bug 的结构性加固)。
    嗅探自身失败时按动作处理:宁可缓存失效,不可放行投毒。
    """
    try:
        return (
            SkillRegistry.find_matching_skill(
                {"input": input_text or "", "tenantId": tenant_id, "slots": {}}
            )
            is not None
        )
    except Exception as err:  # noqa: BLE001
        print(f"[SkillRegistry] Action-query sniff failed, treating as action: {err}")
        return True


__all__ = [
    "BaseSkill",
    "CartManageSkill",
    "OrderAddressModificationSkill",
    "OrderRefundSkill",
    "ProductInquirySkill",
    "ShoppingGuideSkill",
    "SkillRegistry",
    "is_action_query",
]
