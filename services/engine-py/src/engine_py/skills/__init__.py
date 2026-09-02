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


__all__ = [
    "BaseSkill",
    "SkillRegistry",
    "OrderRefundSkill",
    "OrderAddressModificationSkill",
    "ProductInquirySkill",
    "ShoppingGuideSkill",
    "CartManageSkill",
]
