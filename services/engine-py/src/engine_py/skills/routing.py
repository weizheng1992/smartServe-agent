"""技能路由(路由知识单一落点,2026-10-07)。

意图匹配 / 词面兜底 / 资金否决 / 动作形嗅探 / 工具重定向 —— 此前散落五处
(triage 快轨、is_action_query 缓存闸、fallback_dispatcher 自拼正则、
step_engine 服装守卫伸手摸技能私有正则、plan_alignment 词表),一处缺口即
路由漂移(实弹:A11 意图词表缺口、c21 地址倒装形)。

分层纪律(与 cart/ 先例同构):implementation 全在本模块;interface 保持
原位不动 —— ``SkillRegistry.find_matching_skill``(类方法,五个测试桩的
patch 面)与 ``intent_triage_engine`` 的 ``is_action_query`` re-export
(ctx.ns 动态补丁面)原样委托至此。词族仍以 ``intent_registry`` 为单一
事实源,本模块只组合不复制。

匹配函数接受技能序列而非自建注册表(接受依赖,不自造):测试可直接喂
fake 技能,不必动注册中心。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache

from .base_skill import BaseSkill
from .contract import SkillContext

# 售后域技能 category(资金否决只让非售后域技能让位;与 order_skills 声明同值)
AFTER_SALE_CATEGORY = "after_sale"

# 词族(intent_registry)与兜底路由词在本模块为【函数内惰性导入】:
# triage/__init__ 会拉起 intent_triage_engine,而后者 import 本包的
# is_action_query —— 顶层导入会在包半初始化态炸循环(实序依赖,严禁上提)。


def match_skill(skills: Sequence[BaseSkill], context: SkillContext) -> BaseSkill | None:
    """主匹配:已决意图优先(2026-09-22 实弹:上游 triage 判出的意图必须精确
    命中 triggerIntents,严禁被关键词兜底型 can_handle(如导购的「推荐」词面)
    按注册顺序截胡 —— 实弹:「推荐优惠最大的商品」意图层判 promotion_query,
    导购关键词兜底抢先 claim,按销量推荐答非所问);未决输入走 can_handle 词面。"""
    active_intent = context.slots.get("activeIntent") or ""
    if active_intent:
        for skill in skills:
            if active_intent in skill.metadata.get("triggerIntents", []):
                return skill
    for skill in skills:
        if skill.can_handle(context):
            return skill
    return None


def is_action_shaped(skills: Sequence[BaseSkill], input_text: str, tenant_id: str = "") -> bool:
    """业务动作嗅探(语义缓存闸,原 is_action_query 内脏):任一技能声明可处理
    则为动作形。嗅探自身失败按动作处理 —— 宁可缓存失效,不可放行投毒
    (2026-09-04 幻觉加购 bug 的结构性加固)。"""
    try:
        return (
            match_skill(skills, SkillContext(input=input_text or "", tenant_id=tenant_id or "ecommerce"))
            is not None
        )
    except Exception as err:
        print(f"[SkillRouter] Action-query sniff failed, treating as action: {err}")
        return True


def is_money_action_vetoed(input_text: str | None, skill_category: str | None) -> bool:
    """快轨否决纯谓词(多意图一期,2026-09-12):输入含退款/退货词族(∧ 换货/
    换了/换掉)而命中的技能非售后域时拒绝快轨 —— 否则「退了订单X,然后推荐Y」
    被导购 fallback 正则整句吞掉,资金动作静默丢失(实弹矩阵 A6);让位后由
    embedding 锚点/结构化精判接手(那里有 refund 锚点与判定 3)。"""
    from ..triage.intent_registry import MONEY_ACTION_VETO_RE

    return bool(input_text) and bool(MONEY_ACTION_VETO_RE.search(input_text)) and (
        skill_category != AFTER_SALE_CATEGORY
    )


def reroute_tool(tool_name: str, user_input: str) -> str:
    """工具重定向(搭配语义守卫,2026-09-29 实弹「之前只有装备,现在只有衣服」):
    工具选择两条来路(fast-path 关键词 / fallback LLM)都可能把搭配请求写成
    searchProducts 工具子任务(query 自拟单脚)—— 工具路径没有技能 SOP 的
    搭配族补脚/交错合并/合计预算,实弹只推 2 衬衫零装备(同句走技能路径是
    双族+合计)。输入呈搭配形态(搭配/一套/套装 × 衣着锚词)一律改路由导购
    技能;判据引用技能类公开正则(单一事实源,与技能内补脚永不漂移),
    不依赖 LLM 自觉 —— 同取消语闸哲学:确定性代码闸收编 prompt 约束。"""
    if tool_name != "searchProducts":
        return tool_name
    # 局部导入避免包初始化环(__init__ → routing → guide_skills 同包序已安全,
    # 但保持与 step_engine 同款的懒加载习惯,测试桩替换面更稳)
    from .guide_skills import ShoppingGuideSkill

    text = user_input or ""
    if ShoppingGuideSkill.OUTFIT_RE.search(text) and ShoppingGuideSkill.CLOTHING_ANCHOR_RE.search(text):
        return "skill_shopping_guide"
    return tool_name


@lru_cache(maxsize=1)
def _order_query_hint() -> re.Pattern:
    """订单查询意图投影正则(惰性构建:词族在 triage,顶层导入会炸包初始化环)。

    物流/发货单字线索收上词族之家投影(Gen-3 域A);「查/状态」是本面专属词
    留原位(原 fallback_dispatcher._ORDER_QUERY_HINT 迁入)。"""
    from ..triage.intent_registry import ORDER_KEYWORD_FAMILY, _alt, _pick

    return re.compile(
        "查|" + _alt(*_pick(ORDER_KEYWORD_FAMILY, 2, 6)) + "|状态|" + ORDER_KEYWORD_FAMILY[1],
        re.IGNORECASE,
    )


def route_fallback(question: str) -> tuple[bool, str, bool]:
    """降级兜底路由(原 fallback_dispatcher 内联判定迁入):返回
    (wants_promo, order_id, wants_order) —— 优惠词面 / 显式订单号 / 订单查询
    意图(须含「订单」字样,复合句可双中)。执行仍归调用方(dispatcher)。"""
    from ..triage.intent_registry import EXPLICIT_ORDER_ID_RE, PROMOTION_KEYWORDS_RE

    q = (question or "").strip()
    order_hit = EXPLICIT_ORDER_ID_RE.search(q)
    wants_order = bool(order_hit) or (bool(_order_query_hint().search(q)) and "订单" in q)
    return (
        bool(PROMOTION_KEYWORDS_RE.search(q)),
        order_hit.group(0) if order_hit else "",
        wants_order,
    )
