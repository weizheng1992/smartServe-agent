"""购物车管理技能 — 交易与购物车动词的表驱动外壳。

壳只做三件事:声明触发面(can_handle)、把 SkillContext 装配成 CartEnv、
按 ACTION_TABLE 表序分派给动词处理器并把内部结果翻译为 SkillResult。
动词语义(结算/桥接/查看/删除/改量/追问/全量加购/单品加购)全部在
actions.py,话术解析在 resolver.py,卡片组装在 cards.py —— 本文件严禁
长出业务分支(2026-09-15 架构深化①:原 920 行 if 链的分支顺序即语义,
分支间缝隙是 S6/幻影 Nike/双规格去重三类事故的温床)。"""

from __future__ import annotations

import re

from ..base_skill import BaseSkill
from ..contract import SkillContext, SkillResult
from .actions import ACTION_TABLE, CartEnv

_CAN_HANDLE_RE = re.compile(
    r"(?:加购物车|加入购物车|放进购物车|加购|购物车|结算|买第|件加入|款加入|放入购物车|"
    r"第[0-9一二三四五六七八九十两几][件款个双]|要第|删除|移除|删掉|清空|改成\s*\d+|修改为\s*\d+|数量设为\s*\d+)"
)


def _to_result(payload: dict, skill_id: str) -> SkillResult:
    """处理器内部 dict → SkillResult(内部形状是包私有接缝,翻译只在此处)。"""
    extra = payload.get("extra") or {}
    return SkillResult(
        success=payload.get("success", True),
        output=payload.get("output") or "",
        next_action=payload.get("nextAction") or "finish",
        skill_id=payload.get("skillId") or skill_id,
        error=payload.get("error"),
        cards=payload.get("cards"),
        task_plan=payload.get("taskPlan"),
        guide_context=extra.get("guideContext"),
        cart_context=extra.get("cartContext"),
        order_context=extra.get("orderContext"),
    )


class CartManageSkill(BaseSkill):
    metadata = {
        "id": "skill_cart_manage",
        "name": "交易与购物车管理 Agent SOP",
        "description": "参数核验、加购、商品规格变更、购物车结算与优惠汇总",
        "category": "in_sale",
        "triggerIntents": ["cart_manage", "cart_add", "cart_update"],
        "requiredTools": ["addToCart", "getCartSummary", "updateCartItem"],
        "version": "2.0.0",
    }

    def can_handle(self, context: SkillContext) -> bool:
        if super().can_handle(context):
            return True
        return bool(_CAN_HANDLE_RE.search(context.input.lower()))

    async def execute(self, context: SkillContext) -> SkillResult:
        env = CartEnv.from_context(context)
        for action in ACTION_TABLE:
            if action.detect(env):
                return _to_result(await action.handle(env), self.metadata["id"])
        # 表以恒真兜底动词(add)殿后,此处不可达;防御性兜底诚实追问
        return SkillResult(output="请问您想对购物车做什么？可以加购、查看、改量或结算下单。", skill_id=self.metadata["id"])
