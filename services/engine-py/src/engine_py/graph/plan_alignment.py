"""planner 计划后置对齐 —— LLM 深规划的硬约束闸(2026-09-27 立案)。

spec: .scratch/planner-plan-intent-alignment/spec.md
事故:cart_manage 单意图「把销量最好的裤子放到购物车，买2件」被 LLM 深规划拆成
5 步,confirmOrder/modifyCart/checkoutCart 三步是用户从未请求的订单域动作,
且 confirmOrder/modifyCart 根本不在工具注册面(连工具名都是 LLM 发明的);
5 步全绿执行时转移双计恰好撞旧熔断阈值 10,诚实回答被熔断道歉截杀。

纪律:planner prompt 是软约束(规则 8 已同步收紧),本模块是硬约束 —— 每个子
任务的工具/技能动词必须命中检出意图的白名单并集
(triage/intent_registry.IntentSpec.allowed_tools 单一事实源),越界即剪;
checkoutCart 附加下单词门,只认**当前输入**(资金纪律与退款历史回填禁令同款:
上一轮说过「结算」不代表本轮授权)。诚实反问步放行(多意图规则 7 的合法收口);
无动词叙事步按幻觉发明剪(09-13 深规划幻觉叙事事故同源)。全剪回落单步诚实
计划,严禁空计划进 executor。
"""

from __future__ import annotations

import re

from ..triage.intent_registry import INTENT_REGISTRY

# 下单词族(当前输入准入门):与 skills/cart/resolver._CHECKOUT_RE 同口径
# (裸「结算」保持查看摘要旧契约,不开真单,故不在此列)。
CHECKOUT_TRIGGER_RE = re.compile(
    r"(?:结算下单|去结算|提交订单|付款|[^\s]下单|^下单|(?:然后|再|接着|帮忙|帮我|给我)结算)",
    re.IGNORECASE,
)

_TOOL_CALL_RE = re.compile(r"\b(?:Call|Use)\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_SKILL_CALL_RE = re.compile(r"\bExecute\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
_ASK_RE = re.compile(r"\bask\b|询问|反问|追问|请顾客|要求顾客|向顾客", re.IGNORECASE)

# 技能动词 → 意图族(SkillRegistry 注册面技能名的 Execute 形态)。
# CartManageSkill 注册名 CartSkill / ProductInquirySkill 等对齐 skills 包类名。
_SKILL_FAMILY = {
    "CartSkill": "shopping",
    "ShoppingGuideSkill": "shopping",
    "ProductInquirySkill": "shopping",
    "PromotionQuerySkill": "shopping",
    "OrderRefundSkill": "after_sale",
    "OrderAddressModificationSkill": "order",
}


def _allowed_tools_for(intents: list[dict]) -> tuple[set[str], set[str], bool]:
    """检出意图的工具白名单并集、意图族集合、是否存在白名单意图。"""
    allowed: set[str] = set()
    families: set[str] = set()
    has_whitelist = False
    for it in intents:
        spec = INTENT_REGISTRY.get(str(it.get("intent") or ""))
        if spec is None:
            continue
        families.add(spec.family)
        if spec.allowed_tools:
            has_whitelist = True
            allowed.update(spec.allowed_tools)
    return allowed, families, has_whitelist


def _step_verbs(description: str) -> tuple[str | None, str | None]:
    """(工具动词, 技能动词) —— 快轨同款 Call X / Execute Y 两形态。"""
    tool_m = _TOOL_CALL_RE.search(description)
    skill_m = _SKILL_CALL_RE.search(description)
    return (tool_m.group(1) if tool_m else None, skill_m.group(1) if skill_m else None)


def align_plan_to_intents(intents: list[dict], task_plan: dict, input_text: str) -> tuple[dict, list[str]]:
    """LLM 计划后置对齐:返回(对齐后计划, 被剪描述列表)。纯函数,零 IO。

    - 检出意图均无白名单(未登记档位)→ 原样放行:对齐闸只对已登记族生效;
    - 工具动词 ∈ 白名单并集才存活;checkoutCart 须当前输入命中下单词族;
    - 技能动词须映射到检出意图族;诚实反问步放行;无动词叙事步剪(幻觉发明);
    - 全剪回落单步诚实计划(executor 按检出意图域角色分发,同 planner JSON
      解析失败的 step_fallback 先例)。"""
    subtasks = task_plan.get("subtasks") or []
    allowed, families, has_whitelist = _allowed_tools_for(intents)
    if not has_whitelist or not subtasks:
        return task_plan, []

    checkout_allowed = bool(CHECKOUT_TRIGGER_RE.search(input_text or ""))
    kept: list[dict] = []
    pruned: list[str] = []
    for st in subtasks:
        desc = str(st.get("description") or "")
        tool_verb, skill_verb = _step_verbs(desc)
        if tool_verb is None and skill_verb is None:
            if _ASK_RE.search(desc):
                kept.append(st)  # 诚实反问步:多意图规则 7 的合法收口
            else:
                pruned.append(desc)  # 无动词叙事 = 深规划幻觉发明(09-13 同源)
            continue
        if skill_verb is not None:
            if _SKILL_FAMILY.get(skill_verb) in families:
                kept.append(st)
            else:
                pruned.append(desc)
            continue
        if tool_verb == "checkoutCart" and not checkout_allowed:
            pruned.append(desc)  # 资金动作门:「买2件」≠「下单」
            continue
        if tool_verb in allowed:
            kept.append(st)
        else:
            pruned.append(desc)

    if not kept:
        kept = [
            {
                "id": "step_aligned_fallback",
                "description": "Address the customer's request based on detected intents: "
                + ", ".join(sorted({str(it.get("intent") or "") for it in intents})),
                "status": "pending",
            }
        ]
    return {**task_plan, "subtasks": kept}, pruned
