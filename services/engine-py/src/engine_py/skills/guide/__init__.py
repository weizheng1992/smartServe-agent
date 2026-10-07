"""导购子包 — 词族(resolver)/ 检索编排(recommendation)/ 渲染(cards)/
薄壳(skill),结构纪律同 cart/(2026-10-07 自 guide_skills.py 510 行拆解)。"""

from .skill import ProductInquirySkill, ShoppingGuideSkill

__all__ = ["ProductInquirySkill", "ShoppingGuideSkill"]
