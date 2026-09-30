"""任务规划节点 — 镜像 planner.node.ts(470 LOC,全量移植)。

极速直达通道(Fast-Path)优先于 LLM 规划:general_query 旁路、热恢复计划复用、
驳回认知回溯、人工转接直达、复合诉求组装、泛查单直达、订单号关联多意图组装。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from ...approvals import find_approval_by_id, find_latest_approval_by_thread_id
from ...config import settings
from ...event_bus import emit_status
from ...llm import CircuitBreakerOpenError, bind_llm_call_node, get_chat_model
from ...memory import ShortMemory
from ...tenant import get_merchant_display_name
from ...triage.intent_registry import (
    ADDRESS_VERB_FAMILY,
    BEST_SELLER_HINT_RE,
    CHECKOUT_FAMILY,
    GUIDE_CORE_FAMILY,
    METRIC_FAMILY,
    ORDER_LIST_CORE_FAMILY,
    _alt,
    _grp,
    _pick,
)
from ...triage.intent_registry import (
    EXPLICIT_ORDER_ID_RE as _EXPLICIT_ORDER_ID_RE,  # 单号正则收口 intent_registry(工单04)
)
from ..plan_alignment import align_plan_to_intents
from ..state import AgentState, build_history_context
from .utils import extract_order_id

# 泛查单快轨(Gen-3 域A:核心词面上收 intent_registry.ORDER_LIST_CORE_FAMILY,
# 支持退货/订单/买了啥等本面增补词仍留本地拼装)。⚠️ 与
# slot_extractor._GENERAL_LIST_POSITIVE_RE 是孪生词表(nightly G4 钉死
# 双轨),新增措辞两处必须同步 ——「看看我买了啥」曾只认 slot 侧漏 planner 快轨
_GENERAL_ORDER_LIST_RE = re.compile(
    _alt(*(
        _pick(ORDER_LIST_CORE_FAMILY, 3, 2, 0, 4, 1)
        + ("支持退货.*订单", "支持退款.*订单", "可退.*订单", "哪些.*订单", "订单", "我问订单")
        + _pick(ORDER_LIST_CORE_FAMILY, 5)
        + ("买了啥", "买过啥", "我买的东西")
        + _pick(ORDER_LIST_CORE_FAMILY, 6)
    )),
    re.IGNORECASE,
)

# 指标×导购确定性快轨(遗留二期,2026-09-13):指标词族 → rankingMetric 映射
# (METRIC_REGISTRY 5 键:gmv/volume/gross_profit/margin_rate/stock_risk)。
# 词面收上 intent_registry(METRIC_FAMILY/GUIDE_CORE_FAMILY)。
_METRIC_HINT_RE = re.compile(_grp(*_pick(METRIC_FAMILY, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)), re.IGNORECASE)
_SHOPPING_HINT_RE = re.compile(_grp(*_pick(GUIDE_CORE_FAMILY, 0, 1, 2, 3, 8)), re.IGNORECASE)

# 销量榜词族(cart 榜词加购快轨,2026-09-27 立案 planner-plan-intent-alignment)。
# 词面收上 intent_registry.BEST_SELLER_HINT_RE(cart resolver 同源)。
_BEST_SELLER_RE = BEST_SELLER_HINT_RE

# 三段接力轨的结算词与句中地址判据(2026-09-13):「查卖得好的短袖,把第一个
# 加入购物车,地址是X,然后结算」—— 深规划自由发挥曾产出无执行的幻觉叙事
# (历史幻觉单号自增殖),三段确定性编排根治。原为快轨分支内函数局部,注册表
# 化(2026-09-27 nightly #7)提为模块级,值与词族投影逐字不变。
_CHECKOUT_HINT_RE = re.compile(_grp(*_pick(CHECKOUT_FAMILY, 7, 6, 5)))
_STATED_ADDR_RE = re.compile(
    _grp(*_pick(ADDRESS_VERB_FAMILY, 12, 5, 10, 13)) + r"\s*([^,，。]+)"
)


def _ranking_subtask(metric_or_text: str, suffix: str) -> dict:
    """排行快轨子任务单点构造(主快轨与订单动作补偿共用)。

    metric_or_text 传已解析 metric 键(gmv/volume/...)或原文(自动解析)。"""
    metric = (
        metric_or_text
        if metric_or_text in ("gmv", "volume", "gross_profit", "margin_rate", "stock_risk")
        else _ranking_metric_from_text(metric_or_text)
    )
    return {
        "id": f"step_fast_ranking_{suffix}",
        "description": f"Call queryProductRanking with rankingMetric {metric} to fetch real sales ranking",
        "status": "pending",
    }


def _ranking_metric_from_text(text: str) -> str:
    """指标词族 → 排行 metric 键(与 OrderDomainService.METRIC_REGISTRY 同名)。"""
    if re.search(_pick(METRIC_FAMILY, 11)[0], text, re.IGNORECASE):
        return "margin_rate"
    if re.search(_alt(*_pick(METRIC_FAMILY, 3, 4, 5, 6, 7)), text, re.IGNORECASE):
        return "gross_profit"
    if re.search(_alt(*_pick(METRIC_FAMILY, 0, 1)), text, re.IGNORECASE):
        return "gmv"
    if re.search(_pick(METRIC_FAMILY, 8)[0], text, re.IGNORECASE):
        return "stock_risk"
    return "volume"


def planner_llm():
    """深度规划专用模型调用点(max_tokens 封顶)。

    glm-4.7 曾对「退货政策」类简单问题生成 5163 token(73.7s,2026-09-09);
    AI_PLANNER_MAX_TOKENS(默认 2000)封顶防失控,截断 JSON 落 planner 兜底
    单步计划(功能降级不炸会话)。bind 仍走 _ResilientChatOpenAI 公共入口,
    熔断/遥测不丢失。
    """
    return get_chat_model().bind(max_tokens=settings.planner_max_tokens)


# ─── 确定性快轨注册表(nightly #7 / Gen-3 一期③,2026-09-27)─────────────────
# 「意图签名 → 子任务模板」映射表:planner 确定性快轨此前是 7 条各自为政的
# if 分支(每加意图加一条 if,快轨区持续膨胀),现收口为有序规则表 ——
# planner_node 自上而下首个 matches 命中即由 build 组装 (计划, 进度文案) 并
# 直达执行链;新增快轨 = 追加一条注册,不改主循环。
# ⚠️ 表序即优先级,重排等同改行为:metric 轨在复合轨之前(纯查询不被加购半
# 劫持)、泛查单轨在 entity/资金纪律的订单号关联组装之前。以下 build 函数的
# goal/description/进度文案均自原分支逐字迁移,零行为变化。


@dataclass(frozen=True)
class _FastTrackCtx:
    """快轨判定上下文 —— planner_node 在进规则表前一次算定的守卫变量快照。

    守卫标志全是 intents/输入文本上的纯谓词(零副作用,与旧代码无条件求值
    同为每次必算)。唯 _general_order_list_matches 保持原求值点位:其正则对
    input_text 裸取值(旧代码即无 `or ""` 护栏),惰性求值连病态输入
    (state.input=None)的抛错时机都与旧分支一致。
    """

    intents: list[dict]
    single_intent: str | None
    input_text: str
    has_shopping_guide: bool
    has_cart_manage: bool
    has_order_list: bool
    has_order_action: bool
    guide_hint: bool
    has_metric: bool


@dataclass(frozen=True)
class _FastTrackRule:
    """单条快轨规则:matches 命中即 build 出 (task_plan, emit_status 文案)。"""

    name: str
    matches: Callable[[_FastTrackCtx], bool]
    build: Callable[[_FastTrackCtx], tuple[dict, str]]


def _ft_human_escalation_build(_ctx: _FastTrackCtx) -> tuple[dict, str]:
    return {
        "goal": "Escalate conversation to human support operator",
        "subtasks": [
            {
                "id": "step_fast_human_escalation",
                "description": "Trigger human escalation and create pending approval ticket for customer support operator",
                "status": "pending",
            }
        ],
        "currentStepIndex": 0,
    }, "⚡ 极速介入直达：检测到人工客服与熔断诉求，已物理生成人工转接步骤并推入执行链！"


def _ft_metric_single_build(ctx: _FastTrackCtx) -> tuple[dict, str]:
    # 📊 单意图 metric_query 确定性快轨(2026-09-14 nightly 巡检):ADR-0003
    # 规则前置只保证了 triage→planner 段直通,planner→executor 段仍落 LLM
    # 深规划自由发挥 ——「最赚钱的商品排行」_ranking_metric_from_text 明明
    # 能解析出 gross_profit,LLM 深规划却自选 volume(利润榜变销量榜,回复
    # 自称「利润表现优异」实为销量排序)。排行 metric 是纯词表映射,与
    # address_manage 同理必须零 LLM 确定性执行。
    metric = _ranking_metric_from_text(ctx.input_text or "")
    return {
        "goal": "Fetch real product ranking by metric",
        "subtasks": [_ranking_subtask(metric, "0")],
        "currentStepIndex": 0,
    }, f"⚡ 极速直达：识别到经营排行诉求，确定性执行 {metric} 排行检索！"


def _ft_metric_guide_build(ctx: _FastTrackCtx) -> tuple[dict, str]:
    # 📊 指标×导购确定性快轨(遗留二期,2026-09-13):「看看GMV多少,顺便推荐
    # 卖得好的」复合句曾依赖深规划自觉 —— LLM 偶发把 GMV 当后台数据拒答。
    # 排行子任务 + 导购子任务确定性组装,零 LLM 拒答面;资金/订单动作在场
    # 时不劫持(让位深规划按资金纪律编排)。
    ranking_metric = _ranking_metric_from_text(ctx.input_text or "")
    return {
        "goal": "Fetch real sales metrics and shopping recommendations",
        "subtasks": [
            _ranking_subtask(ranking_metric, "0"),
            {
                "id": "step_fast_guide_1",
                "description": f"Execute ShoppingGuideSkill for input: {ctx.input_text}",
                "status": "pending",
            },
        ],
        "currentStepIndex": 0,
    }, "⚡ 极速规划直达：识别到经营数据+导购复合诉求，已组装排行与导购双子任务流！"


def _ft_guide_cart_build(ctx: _FastTrackCtx) -> tuple[dict, str]:
    # 🛒 推荐×全量加购确定性快轨(2026-09-13 一句话接力):「推荐X，都要了」
    # 先导购(写候选,数量语义生效)后购物车全量入车 —— 零 LLM,严禁 guide
    # 快轨单技能吞掉加购半。
    # 结算词与句中地址(2026-09-13 三段接力):命中结算词则尾接 checkoutCart
    # 子任务,句中带地址随子任务透传,否则落默认地址。
    input_text = ctx.input_text
    fast_subtasks = [
        {
            "id": "step_fast_guide_0",
            "description": f"Execute ShoppingGuideSkill for input: {input_text}",
            "status": "pending",
        },
        {
            "id": "step_fast_cart_1",
            "description": f"Execute CartSkill for input: {input_text}",
            "status": "pending",
        },
    ]
    has_checkout = bool(_CHECKOUT_HINT_RE.search(input_text or ""))
    if has_checkout:
        addr = _STATED_ADDR_RE.search(input_text or "")
        shipping = (
            f"shipping to {addr.group(1).strip()}"
            if addr
            else "shipping to the customer's default address"
        )
        fast_subtasks.append(
            {
                "id": "step_fast_checkout_2",
                "description": (
                    f"Call checkoutCart to place a real order from the current cart items, {shipping}"
                ),
                "status": "pending",
            }
        )
    return {
        "goal": "Recommend products then add them to cart" + (" and check out" if has_checkout else ""),
        "subtasks": fast_subtasks,
        "currentStepIndex": 0,
    }, "⚡ 极速规划直达：识别到推荐+全量加购诉求，已组装导购与购物车双子任务流！"


def _ft_bestseller_cart_build(ctx: _FastTrackCtx) -> tuple[dict, str]:
    # 🛒 榜词加购确定性快轨(2026-09-27 立案 planner-plan-intent-alignment):
    # cart_manage「销量榜词+加购」形态此前无任何快轨,直坠 LLM 深规划自由
    # 发挥成 5 步(排行/加购/确认订单/改量/结算)—— 后三步用户从未请求,
    # 转移双计撞旧熔断阈值(09:42 实弹熔断事故)。此处确定性单步收口,零
    # LLM 规划:只排 CartSkill,技能内 2.6.53 榜词分支诚实反问在售真货,
    # 严禁静默落候选[0]。刻意不排 queryProductRanking —— 排行是全店榜无
    # 品类过滤,「销量最好的裤子」会被答成全店第一(2.6.53 同源谎言面),
    # 排行步待榜单支持品类过滤后再入计划。判据不带 metric_query 否决:
    # 「销量最好」实弹必被 triage 拆出 metric 半(09-27 实弹取证),全店
    # 榜同样答不了品类最优,CartSkill 诚实反问是两类语义的并集正解;
    # 非榜词的 metric 复合(「查下GMV顺便加购」)不命中榜词 RE,照旧深规划。
    return {
        "goal": "Add requested products to cart with honest shelf guidance",
        "subtasks": [
            {
                "id": "step_fast_bestseller_cart_0",
                "description": f"Execute CartSkill for input: {ctx.input_text}",
                "status": "pending",
            }
        ],
        "currentStepIndex": 0,
    }, "⚡ 极速规划直达：识别到销量榜加购诉求，确定性走购物车技能诚实引导！"


def _ft_composite_order_list_build(ctx: _FastTrackCtx) -> tuple[dict, str]:
    fast_subtasks: list[dict] = []
    if ctx.has_cart_manage:
        fast_subtasks.append(
            {"id": "step_fast_cart_0", "description": f"Execute CartSkill for input: {ctx.input_text}", "status": "pending"}
        )
    else:
        fast_subtasks.append(
            {"id": "step_fast_guide_0", "description": f"Execute ShoppingGuideSkill for input: {ctx.input_text}", "status": "pending"}
        )
    fast_subtasks.append(
        {"id": "step_fast_list_orders_1", "description": "Call listUserOrders to fetch recent orders", "status": "pending"}
    )
    return {
        "goal": "Execute composite shopping and order query subtasks",
        "subtasks": fast_subtasks,
        "currentStepIndex": 0,
    }, f"⚡ 极速规划直达：识别到复合诉求，已智能组装 {len(fast_subtasks)} 项子任务流并投入执行引擎！"


def _ft_general_order_list_build(_ctx: _FastTrackCtx) -> tuple[dict, str]:
    return {
        "goal": "List recent orders for customer",
        "subtasks": [
            {"id": "step_fast_list_orders", "description": "Call listUserOrders to fetch recent orders", "status": "pending"}
        ],
        "currentStepIndex": 0,
    }, "⚡ 极速规划直达：检测到客户订单列表查询诉求，秒级调度 listUserOrders 工具进行物理查单！"


def _ft_general_order_list_matches(ctx: _FastTrackCtx) -> bool:
    # 泛查单判定与旧分支同点位求值(含 is_explicit_order_id 的裸 input_text
    # 正则),命中条件 = 查单族泛指词面 × 单意图 × 无显式单号。
    is_explicit_order_id = bool(_EXPLICIT_ORDER_ID_RE.search(ctx.input_text))
    return (
        ctx.single_intent in ("order_status", "order_query")
        and bool(_GENERAL_ORDER_LIST_RE.search(ctx.input_text))
        and not is_explicit_order_id
        and len(ctx.intents) == 1
    )


_FAST_TRACK_RULES: tuple[_FastTrackRule, ...] = (
    _FastTrackRule(
        "human_escalation",
        lambda ctx: ctx.single_intent == "human_escalation",
        _ft_human_escalation_build,
    ),
    _FastTrackRule(
        "metric_single",
        lambda ctx: len(ctx.intents) == 1 and ctx.single_intent == "metric_query",
        _ft_metric_single_build,
    ),
    _FastTrackRule(
        "metric_x_guide",
        lambda ctx: ctx.has_metric and ctx.guide_hint and not ctx.has_order_action and not ctx.has_cart_manage,
        _ft_metric_guide_build,
    ),
    _FastTrackRule(
        "guide_x_cart",
        lambda ctx: ctx.has_shopping_guide and ctx.has_cart_manage and not ctx.has_order_action,
        _ft_guide_cart_build,
    ),
    _FastTrackRule(
        "bestseller_cart",
        lambda ctx: (
            ctx.has_cart_manage
            and not ctx.has_shopping_guide
            and not ctx.has_order_action
            and not ctx.has_order_list
            and bool(_BEST_SELLER_RE.search(ctx.input_text or ""))
        ),
        _ft_bestseller_cart_build,
    ),
    _FastTrackRule(
        "composite_order_list",
        lambda ctx: (ctx.has_shopping_guide or ctx.has_cart_manage)
        and ctx.has_order_list
        and len(ctx.intents) >= 2,
        _ft_composite_order_list_build,
    ),
    _FastTrackRule(
        "general_order_list",
        _ft_general_order_list_matches,
        _ft_general_order_list_build,
    ),
)


async def planner_node(state: AgentState) -> dict:
    bind_llm_call_node("planner")
    intents = state.get("intents") or []
    input_text = state.get("input", "")
    job_id = state.get("job_id")

    # 🧠 general_query 极简旁路:Null 步骤瞬间穿透到 Finish
    if len(intents) == 1 and intents[0].get("intent") == "general_query":
        direct_plan = {
            "goal": "Bypass planner loop and respond to general query directly",
            "subtasks": [
                {"id": "respond_general", "description": "Present general query response to user", "status": "pending"}
            ],
            "currentStepIndex": 0,
        }
        if job_id:
            await emit_status(
                job_id,
                "检测到日常问询或欢迎语诉求，系统已完美启用【极速直达旁路】，无需进入复杂的工具规划与自旋校验环...",
                node="planner",
                plan=direct_plan,
            )
        return {"task_plan": direct_plan, "global_transitions_count": 1}

    if job_id:
        await emit_status(
            job_id, "正在根据分类意图，由大模型动态生成高精准子步骤执行规划...", node="planner"
        )

    prior_plan = state.get("task_plan") or {}
    prior_subtasks = prior_plan.get("subtasks") or []

    # 🛡️ Plan-Preservation Bypass(HOT-RESUME):审批已决议则 100% 复用历史计划
    if prior_subtasks:
        current_step_index = prior_plan.get("currentStepIndex", 0)
        current_step = (
            prior_subtasks[current_step_index] if 0 <= current_step_index < len(prior_subtasks) else None
        )
        if current_step and (
            (current_step.get("result") or {}).get("waitingForApproval") or current_step.get("status") == "pending"
        ):
            try:
                approval_id = (current_step.get("result") or {}).get("approvalId")
                latest_approval = (
                    await find_approval_by_id(approval_id)
                    if approval_id
                    else await find_latest_approval_by_thread_id(state.get("thread_id", ""))
                )
                if latest_approval and latest_approval["status"] in (
                    "approved",
                    "cancelled",
                    "resolved_by_human",
                ):
                    status_label = (
                        "核准"
                        if latest_approval["status"] == "approved"
                        else "人工接管办结"
                        if latest_approval["status"] == "resolved_by_human"
                        else "取消"
                    )
                    if job_id:
                        await emit_status(
                            job_id,
                            f"🔄 恢复计划：检测到历史执行工单已人工审核决议为 [{status_label}]，"
                            "跳过大模型规划，100% 物理复用历史步骤并精确恢复执行流！",
                            node="planner",
                            plan=prior_plan,
                        )
                    return {"task_plan": prior_plan, "global_transitions_count": 1}
            except Exception as db_err:
                print(f"[Planner Bypass] Failed to check approval status for bypass: {db_err}")

    # 🧠 Cognitive State Backtracking:管理员驳回 → failed/rejectedByAdmin 标记 + 重规划上下文
    rejection_context = ""
    is_system_resume = isinstance(input_text, str) and input_text.startswith("System:")
    if is_system_resume and prior_subtasks:
        current_step_index = prior_plan.get("currentStepIndex", 0)
        step = prior_subtasks[current_step_index] if 0 <= current_step_index < len(prior_subtasks) else None
        step_approval_id = (step.get("result") or {}).get("approvalId") if step else None

        latest_approval = None
        try:
            latest_approval = (
                await find_approval_by_id(step_approval_id)
                if step_approval_id
                else await find_latest_approval_by_thread_id(state.get("thread_id", ""))
            )
        except Exception as db_err:
            print(f"[Planner Rejection Check] Failed to check latest approval for backtracking: {db_err}")

        if latest_approval and latest_approval["status"] == "rejected":
            if step and (
                (step.get("result") or {}).get("waitingForApproval")
                or step.get("status") in ("pending", "executing")
            ):
                rejection_reason = (
                    latest_approval["actionPayload"].get("rejectionReason")
                    or latest_approval.get("reason")
                    or "No reason provided"
                )
                prior_subtasks[current_step_index] = {
                    **step,
                    "status": "failed",
                    "result": {
                        **(step.get("result") or {}),
                        "rejectedByAdmin": True,
                        "rejectionReason": rejection_reason,
                    },
                }
                prior_plan = {**prior_plan, "subtasks": prior_subtasks}

        rejected_step = next(
            (st for st in prior_subtasks if st.get("status") == "failed" and (st.get("result") or {}).get("rejectedByAdmin")),
            None,
        )
        if rejected_step:
            rejection_reason = (rejected_step.get("result") or {}).get("rejectionReason") or "No reason provided"
            rejection_context = (
                f'\n\n[CRITICAL ADVISORY]: A previous step "{rejected_step.get("description")}" was '
                f'REJECTED by the Administrator.\nRejection feedback/reason: "{rejection_reason}".\n'
                "Please replan and output an alternative approach that respects this rejection. Do NOT suggest "
                "the same rejected action. If a smaller refund was suggested, adjust the amount. If the user "
                "request cannot be fulfilled, generate a step to explain the reason politely to the user."
            )

    # 📦 SaaS Contextual RAG 注入
    rag_context = ""
    rag_documents = state.get("rag_documents") or []
    if rag_documents:
        formatted_docs = "\n".join(
            f'[Store Policy Rule {idx + 1}] (Context Summary: {doc.get("contextualSummary") or "N/A"}): '
            f'"{doc.get("chunkText")}"'
            for idx, doc in enumerate(rag_documents)
        )
        rag_context = (
            f"\n\n[RELEVANT BUSINESS POLICIES & KNOWLEDGE BASE]:\n{formatted_docs}\n"
            "Strictly adhere to these store policies while making the plan. If a policy specifies return "
            "timelines, tag conditions, or shipping methods, make sure any proposed subtasks or user "
            "communication steps strictly follow these rules."
        )

    tenant_id = str((state.get("business_config") or {}).get("businessId") or "ecommerce").lower()
    brand_name = get_merchant_display_name(tenant_id)
    default_system_prompt = (
        f"You are an advanced, professional AI Customer Support Agent representing {brand_name}. "
        "Help users resolve order, shipping, and refund queries."
    )
    business_system_prompt = (state.get("business_config") or {}).get("systemPrompt")
    system_prompt = (
        business_system_prompt
        if business_system_prompt and brand_name in business_system_prompt
        else default_system_prompt
    )
    tenant_context = (
        f"\n\n[MULTI-TENANT ISOLATION BOUNDARY]:\n"
        f"You are an AI Customer Support Agent representing: {brand_name} (Merchant identifier: {tenant_id}).\n"
        f"- Always plan subtasks and customer responses representing {brand_name}.\n"
        f"- You must strictly align your plan with {brand_name}'s store policies and system tools.\n"
        f'- In all user-facing subtasks, refer to the store strictly by its real brand name "{brand_name}".\n'
        "- If the customer explicitly asks to query or operate on unrelated external brands/stores, plan to "
        f"politely refuse and clarify that you only support {brand_name}."
        # ADR-0002/0003:经营口径排行是本店在售商品的合法客服能力(商户真订单
        # 聚合,非后台报表),严禁把它当敏感数据拒答或改道导购浏览。
        "\n- Product ranking asks (热销/排行/排名/Top N, by GMV/销量/毛利/毛利率/库存) are a "
        "legitimate storefront capability backed by real sales data: plan a step that calls "
        "'queryProductRanking' with the matching rankingMetric (gmv/volume/gross_profit/margin_rate/"
        "stock_risk). NEVER refuse these as 'backend reports' and NEVER substitute them with "
        "product recommendations."
    )

    # 🚀 会话上下文记忆注入
    short_memory = state.get("short_memory") or []
    if not short_memory:
        short_memory = await ShortMemory(state.get("thread_id", "")).get_messages()
    history_context = ""
    if short_memory:
        formatted_history = build_history_context(short_memory)
        if formatted_history:
            history_context = (
                f"\n\n[CONVERSATION HISTORY (PAST TURNS)]:\n{formatted_history}\n\n"
                "[CRITICAL DIRECTIVE]: Carefully read the conversation history above. If the customer is "
                "requesting a refund or action in their current input, and they have already provided a "
                "specific order ID in previous turns (or you have already queried it successfully), you MUST "
                "extract and use that order ID to formulate your subtasks (e.g. processRefund with orderId: "
                "ORD-98712). DO NOT plan to ask the customer for the order ID again if it was already "
                "mentioned or established in the history!"
            )

    # ⚡ 极速直达通道(Fast-Path,零 LLM 开销)
    if not rejection_context and intents:
        single_intent = intents[0].get("intent")

        # 🏠 地址簿快轨(多意图一期,2026-09-12):单 address_manage 直达
        # saveUserAddress/getUserAddresses 子任务,零 LLM —— 写动作必须确定性,
        # 严禁落深规划自由发挥(A11 实弹曾编造假改派流程)。评审缺陷修复:
        # 复合形(address_manage+cart_manage 等)不得被本快轨砍掉次要意图,
        # len==1 闸保复合形落深规划按规则 7 双编排。
        if len(intents) == 1 and single_intent == "address_manage":
            addr_entities = intents[0].get("entities") or {}
            if addr_entities.get("addressAction") == "list":
                fast_plan = {
                    "goal": "List saved delivery addresses for customer",
                    "subtasks": [
                        {
                            "id": "step_fast_address_book_list",
                            "description": "Call getUserAddresses to list the customer's saved delivery addresses",
                            "status": "pending",
                        }
                    ],
                    "currentStepIndex": 0,
                }
            elif addr_entities.get("addressAction") == "delete":
                # persona-hardening 14(2026-09-30):本分支曾在此被下方 set_default
                # 计划无条件覆盖(无 elif 隔开)—— 删地址实际派发 setDefaultAddress,
                # 副作用与用户诉求相反。delete 回归本义,set_default 另立分支。
                fast_plan = {
                    "goal": "Delete saved delivery addresses for customer",
                    "subtasks": [
                        {
                            "id": "step_fast_address_delete",
                            "description": (
                                f"Call deleteUserAddress to delete the customer's saved delivery address. "
                                f"Customer said: {input_text}. If ambiguous, call getUserAddresses first "
                                f"and confirm with the customer which address to delete."
                            ),
                            "status": "pending",
                        }
                    ],
                    "currentStepIndex": 0,
                }
            elif addr_entities.get("addressAction") == "set_default":
                target = (input_text or "").strip()
                fast_plan = {
                    "goal": "Set default delivery address for customer",
                    "subtasks": [
                        {
                            "id": "step_fast_address_default",
                            "description": (
                                f"Call setDefaultAddress to set the customer's default delivery address. "
                                f"Extract the receiverName (收件人姓名, e.g. 王五/张伟) from the customer's "
                                f"words: {target} — pass it as the receiverName argument. If ambiguous, first "
                                f"call getUserAddresses and mention the candidates by recipientName in your reply."
                            ),
                            "status": "pending",
                        }
                    ],
                    "currentStepIndex": 0,
                }
            elif addr_entities.get("addressAction") == "save" and not (
                intents[0].get("missingSlots") or []
            ):
                field_line = "、".join(
                    f"{key} {value}" for key, value in addr_entities.items() if key != "addressAction"
                )
                fast_plan = {
                    "goal": "Save new delivery address to customer address book",
                    "subtasks": [
                        {
                            "id": "step_fast_save_address",
                            "description": (
                                "Call saveUserAddress to save a new delivery address with: "
                                f"{field_line}"
                            ),
                            "status": "pending",
                        }
                    ],
                    "currentStepIndex": 0,
                }
            else:
                fast_plan = None
            if fast_plan is not None:
                if job_id:
                    await emit_status(
                        job_id,
                        "⚡ 极速直达：识别到地址簿管理诉求，已直达地址簿工具执行链！",
                        node="planner",
                        plan=fast_plan,
                    )
                return {"task_plan": fast_plan, "short_memory": short_memory, "global_transitions_count": 1}

        # 🧠 偏好记录快轨(persona-hardening 12,2026-09-30):单 preference_record
        # 直达 recordUserPreference 子任务,零 LLM —— 写动作必须确定性。实弹:
        # 深规划的记录子任务被对齐闸整批剪除(意图层白名单缺注册),写路死,
        # finish 还即兴假宣称「已成功记录」。检测器抽取的明示偏好值随描述
        # 下行,执行器快路径直配成真工具调用。
        if len(intents) == 1 and single_intent == "preference_record":
            pref_entities = intents[0].get("entities") or {}
            stated = str(pref_entities.get("statedPreference") or "").strip()
            pref_desc = (
                "Call recordUserPreference to record the customer's stated preference. "
                f"Customer said: {input_text}."
            )
            if stated:
                pref_desc += f" Stated preference: {stated}."
            pref_fast_plan = {
                "goal": "Record the customer's stated preference into profile memory",
                "subtasks": [
                    {
                        "id": "step_fast_record_preference",
                        "description": pref_desc,
                        "status": "pending",
                    }
                ],
                "currentStepIndex": 0,
            }
            if job_id:
                await emit_status(
                    job_id,
                    "⚡ 极速直达：识别到偏好记录诉求，已直达画像记录工具执行链！",
                    node="planner",
                    plan=pref_fast_plan,
                )
            return {"task_plan": pref_fast_plan, "short_memory": short_memory, "global_transitions_count": 1}

        # 📋 确定性快轨注册表(nightly #7):守卫变量一次算定,规则表自上而下
        # 首个命中即组装 (计划, 进度文案) 直达执行链。守卫标志全是纯谓词,
        # 与旧代码同为无条件求值;表序即优先级(见 _FAST_TRACK_RULES 头注)。
        has_shopping_guide = any(i.get("intent") == "shopping_guide" for i in intents)
        has_cart_manage = any(i.get("intent") == "cart_manage" for i in intents)
        has_order_list = any(i.get("intent") in ("order_status", "order_query") for i in intents)
        has_order_action = any(
            i.get("intent")
            in ("refund", "order_return", "order_modify_address", "order_cancel", "order_status", "order_query")
            for i in intents
        )
        metric_hint = _METRIC_HINT_RE.search(input_text or "")
        guide_hint = bool(has_shopping_guide) or bool(_SHOPPING_HINT_RE.search(input_text or ""))
        has_metric = any(i.get("intent") == "metric_query" for i in intents) or bool(metric_hint)
        fast_ctx = _FastTrackCtx(
            intents=intents,
            single_intent=single_intent,
            input_text=input_text,
            has_shopping_guide=has_shopping_guide,
            has_cart_manage=has_cart_manage,
            has_order_list=has_order_list,
            has_order_action=has_order_action,
            guide_hint=guide_hint,
            has_metric=has_metric,
        )
        for _rule in _FAST_TRACK_RULES:
            if not _rule.matches(fast_ctx):
                continue
            fast_plan, fast_status = _rule.build(fast_ctx)
            if job_id:
                await emit_status(job_id, fast_status, node="planner", plan=fast_plan)
            return {"task_plan": fast_plan, "short_memory": short_memory, "global_transitions_count": 1}

        entity_order_id = next(
            (i.get("entities", {}).get("orderId") for i in intents if i.get("entities", {}).get("orderId")), None
        )
        extracted_order_id = entity_order_id or extract_order_id(input_text, None, short_memory)

        # 资金动作(退款/退货)禁止经历史回填拿订单号直达 fast-path:历史最后提及
        # 的订单常是旧回合已退款的订单(2026-09-05 双退款事故)。当前输入未指明
        # 订单号时降级到 LLM 深度规划,由其规划向用户澄清退哪一单。
        if any(i.get("intent") in ("refund", "order_return") for i in intents) and not (
            entity_order_id or _EXPLICIT_ORDER_ID_RE.search(input_text)
        ):
            extracted_order_id = None

        if extracted_order_id:
            action_intents = [
                i
                for i in intents
                if i.get("intent")
                in ("order_status", "refund", "order_modify_address", "order_query", "order_return")
            ]

            if action_intents:
                fast_subtasks = []
                for idx, item in enumerate(action_intents):
                    suffix = f"_{idx}" if len(action_intents) > 1 else ""
                    intent = item["intent"]
                    condition = item.get("condition")
                    if intent in ("order_status", "order_query"):
                        fast_subtasks.append(
                            {
                                "id": f"step_fast_status{suffix}",
                                "description": f"Call getOrderStatus for order {extracted_order_id}",
                                "status": "pending",
                                **({"condition": condition} if condition else {}),
                            }
                        )
                    elif intent in ("refund", "order_return"):
                        fast_subtasks.append(
                            {
                                "id": f"step_fast_refund{suffix}",
                                "description": f"Call processRefund for order {extracted_order_id}",
                                "status": "pending",
                                **({"condition": condition} if condition else {}),
                            }
                        )
                    elif intent == "order_modify_address":
                        task_spec = item.get("taskSpec") or {}
                        target_address = (task_spec.get("slots") or {}).get("newAddress") or "客户指定新地址"
                        fast_subtasks.append(
                            {
                                "id": f"step_fast_change_address{suffix}",
                                "description": f"Call changeShippingAddress for order {extracted_order_id} with new address {target_address}",
                                "status": "pending",
                                **({"condition": condition} if condition else {}),
                            }
                        )

                has_conditional_step = any(st.get("condition") for st in fast_subtasks)
                has_status_query = any("step_fast_status" in st["id"] for st in fast_subtasks)
                if has_conditional_step and not has_status_query:
                    fast_subtasks.insert(
                        0,
                        {
                            "id": "step_fast_status_pre",
                            "description": f"Call getOrderStatus for order {extracted_order_id}",
                            "status": "pending",
                        },
                    )

                # 复合偿付(遗留二期,2026-09-13):订单动作快轨只认订单族意图,
                # 句中同现的指标/导购诉求此前被静默吞 —— 尾追排行/导购子任务,
                # 复合请求每个动作都有子任务(rule 7 的确定性兑现)。排行偿付须
                # 指标×导购双命中(「那鞋销量不行」不得凭空造排行步骤)。
                wants_metric = bool(_METRIC_HINT_RE.search(input_text or "")) and (
                    bool(has_shopping_guide) or bool(_SHOPPING_HINT_RE.search(input_text or ""))
                )
                if wants_metric:
                    fast_subtasks.append(_ranking_subtask(input_text, "m"))
                if has_shopping_guide or _SHOPPING_HINT_RE.search(input_text or ""):
                    fast_subtasks.append(
                        {
                            "id": "step_fast_guide_m",
                            "description": f"Execute ShoppingGuideSkill for input: {input_text}",
                            "status": "pending",
                        }
                    )

                if fast_subtasks:
                    first_intent = action_intents[0]["intent"]
                    if first_intent in ("order_status", "order_query"):
                        goal_action = "Query status"
                    elif first_intent in ("refund", "order_return"):
                        goal_action = "Process refund"
                    elif first_intent == "order_modify_address":
                        goal_action = "Change shipping address"
                    else:
                        goal_action = first_intent

                    fast_plan = {
                        "goal": (
                            f"{goal_action} for order {extracted_order_id}"
                            if len(fast_subtasks) == 1
                            else f"Execute multiple subtasks for order {extracted_order_id}"
                        ),
                        "subtasks": fast_subtasks,
                        "currentStepIndex": 0,
                    }
                    if job_id:
                        await emit_status(
                            job_id,
                            f"⚡ 极速规划直达：关联订单号 [{extracted_order_id}]，快速生成 "
                            f"{len(fast_subtasks)} 项多意图执行步骤，绕过大模型规划消耗！",
                            node="planner",
                            plan=fast_plan,
                        )
                    return {
                        "task_plan": fast_plan,
                        "short_memory": short_memory,
                        "global_transitions_count": 1,
                    }

    # 🧠 LLM 深度规划
    prompt = (
        f'System Instruction Context: "{system_prompt}"{tenant_context}\n'
        f"Based on the intents: {json.dumps(intents, ensure_ascii=False, default=str)} and input: "
        f'"{input_text}", generate a sequence of structured steps (a plan) to satisfy the request.'
        f"{rejection_context}{rag_context}{history_context}\n\n"
        "[CRITICAL MULTI-TURN MEMORY & RETRIEVAL DIRECTIVES]:\n"
        "1. Carefully inspect the [CONVERSATION HISTORY (PAST TURNS)] above. If the customer has already "
        'mentioned a specific Order ID (e.g., "ORD-98712") in previous turns, or if an Order ID was '
        "successfully checked earlier, you MUST assume the customer's current request (for refund, status "
        "query, or returns) is regarding that EXACT Order ID!\n"
        '2. If the customer asks "我还有其他订单吗" (Do I have other orders?), "查询我名下的订单" (Query '
        'orders under my name), "我可以退货的订单有哪些" (Which orders can I return?), or wants to list '
        'their order history / eligible return orders, you MUST plan a step to call the "listUserOrders" '
        "tool to fetch their recent order list.\n"
        '3. If an Order ID (like "ORD-98712") is present in the history, bypass any placeholder check '
        "steps, and directly plan a concrete step to execute the requested action. For example: \"Call the "
        "processRefund tool with orderId 'ORD-98712' to initiate the return/refund in our systems.\"\n"
        '4. If NO Order ID exists anywhere in the conversation history, and they are asking for an order '
        'operation (refund, tracking), you should plan a step to call "listUserOrders" first to dynamically '
        "find their recent orders, or ask the customer to provide their Order ID if listUserOrders is "
        "unavailable or returns nothing.\n"
        '5. DO NOT plan a step to call "processRefund" when the customer is merely asking which orders are '
        'eligible for return! Only plan "processRefund" when the customer specifies a concrete order to be '
        "refunded.\n"
        "6. EXCEPTION to rule 1 for refunds: the history-inheritance MUST NOT apply to refund/return "
        "(processRefund) steps. Only plan a processRefund step when the customer's CURRENT request names a "
        "specific order ID, or they explicitly confirm one in this turn. If the current request contains no "
        "order ID, plan a step to ASK the customer which order to refund instead — the last-mentioned order "
        "in history may be a stale one that was already refunded.\n\n"
        "7. MULTI-INTENT REQUESTS (do-what-you-can): when the intents list contains multiple entries, plan "
        "subtasks covering EVERY actionable intent. If an intent is missing a required slot (its "
        "missingSlots field, e.g. a refund without orderId), still plan the doable subtasks first and end "
        "the plan with exactly ONE subtask that asks the customer for the missing information. NEVER drop "
        "or silently ignore part of a compound request — every requested action must either get a subtask "
        "or an explicit ask.\n"
        "7.5 URGE-SHIPPING REQUESTS (催发货/催物流/急用): these are order-status inquiries with an "
        "urgent tone — plan getOrderStatus or listUserOrders and reply with the real status and expected "
        "timeline. NEVER create a human escalation ticket just because the customer urges or sounds "
        "impatient; escalation is ONLY for an explicit 转人工/找人工 request.\n"
        "8. ORDER PLACEMENT: the chat assistant CAN place a REAL order from the current shopping cart via "
        "checkoutCart (real stock, real merchant order). When the customer asks to check out / place the "
        "order (结算下单/下单) and the product is already clear, plan a checkoutCart step; when the product "
        "is not yet chosen, plan addToCart (product clear from context) and the final reply guides them to "
        "say 结算下单. NEVER plan a step calling createOrder — it does not exist. "
        "QUANTITY vs ORDER PLACEMENT (资金纪律): 「买N件/来两件/拍N件」 is a QUANTITY slot of addToCart — "
        "write the quantity into the addToCart step description (e.g. addToCart quantity 2); it is NEVER an "
        "order-placement request. ONLY explicit 结算/下单/提交订单/付款 vocabulary in the CURRENT customer "
        "message authorizes a checkoutCart step — an add-to-cart request must NEVER produce confirmOrder or "
        "checkoutCart subtasks, and quantity folding into addToCart means a separate modifyCart/updateCartItem "
        "step is redundant (plan it only when the customer asks to CHANGE an existing cart item). "
        "TOOL FIDELITY: plan only real registered tool names (getOrderStatus, processRefund, listUserOrders, "
        "changeShippingAddress, queryProductRanking, searchProducts, queryProductSkus, queryProductReviews, "
        "compareProducts, addToCart, updateCartItem, getCartSummary, checkoutCart, saveUserAddress, "
        "getUserAddresses, deleteUserAddress, setDefaultAddress, recordUserPreference, applyAfterSale, "
        "queryPackageTracking) — "
        "invented names like confirmOrder or modifyCart do not exist and will be pruned. "
        "PREFERENCE FIDELITY: for explicit preference-recording requests (记住/记录/保存 我的偏好, intent "
        "preference_record), plan a recordUserPreference step written in verb form (Call recordUserPreference ...) "
        "— it is a real capability; do not merely narrate that the preference will be remembered. "
        "ADDRESS FIDELITY: if the customer stated a shipping address in this turn (e.g. 地址是…/寄到…), "
        "that address belongs to the NEW order — write it into the checkoutCart step description "
        "(shipping to <address>) and NEVER plan a changeShippingAddress step against a historical order "
        "for it. "
        "For address book management (创建/查看收货地址, intent address_manage), plan saveUserAddress or "
        "getUserAddresses steps — these are real capabilities.\n\n"
        "Return a JSON object with:\n"
        '- "goal": overall goal description\n'
        '- "subtasks": array of objects with keys "id" (unique string), "description" (what to do, e.g., '
        "call tool getOrderStatus, or ask user for confirmation).\n"
        "Return ONLY the raw JSON object. Do not include markdown or backticks."
    )

    try:
        response = await planner_llm().ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        llm_plan_parsed = True
        try:
            clean_response = content.strip()
            clean_response = re.sub(r"^```json\s*", "", clean_response)
            clean_response = re.sub(r"```$", "", clean_response).strip()
            plan = json.loads(clean_response)
        except Exception:
            # 截断/脏输出的确定性兜底:per-intent 单步,planner 亲造且与检出
            # 意图一一对应 —— 天然对齐,不过 align 闸(闸只管 LLM 自由输出,
            # 「Handle X process」无动词是形态而非幻觉)。
            llm_plan_parsed = False
            plan = {
                "goal": "Address customer request",
                "subtasks": [
                    {"id": f"step_{idx}", "description": f"Handle {it.get('intent')} process", "status": "pending"}
                    for idx, it in enumerate(intents)
                ],
            }

        task_plan = {
            "goal": plan.get("goal") or "Handle customer request",
            "subtasks": [
                {"id": sub.get("id"), "description": sub.get("description"), "status": "pending"}
                for sub in (plan.get("subtasks") or [])
            ],
            "currentStepIndex": 0,
        }

        # 🛡️ 计划后置对齐(2026-09-27 立案 planner-plan-intent-alignment):
        # LLM 深规划的子任务逐条对齐检出意图白名单(intent_registry.allowed_tools
        # 单一事实源),越界即剪 —— prompt 规则 8 是软约束,这里是硬约束。
        # 仅 LLM 解析成功的计划过闸;截断兜底的 per-intent 计划系确定性构造,
        # 天然对齐不过闸。剪枝留痕(租户/thread/被剪描述),不阻断不透出
        # (OQ3 裁决:由 finish 终稿自然指引)。
        pruned_steps: list[str] = []
        if llm_plan_parsed:
            task_plan, pruned_steps = align_plan_to_intents(intents, task_plan, input_text)
        if pruned_steps:
            print(
                f"[Planner][PlanAlignment] pruned {len(pruned_steps)} out-of-intent subtask(s) "
                f"tenant={tenant_id} thread={state.get('thread_id')}: {pruned_steps}"
            )

        if job_id:
            await emit_status(
                job_id,
                f"子步骤物理规划成功！目标：{task_plan['goal']}，拆解为 {len(task_plan['subtasks'])} 个子任务。",
                node="planner",
                plan=task_plan,
            )
        return {"task_plan": task_plan, "short_memory": short_memory, "global_transitions_count": 1}
    except CircuitBreakerOpenError:
        # 上游 LLM 熔断非节点级可恢复:上抛 run_agent 走 job 级降级(兜底计划仅面向规划输出类失败)
        raise
    except Exception as err:
        print(f"plannerNode failed, falling back to default single-step plan: {err}")
        return {
            "task_plan": {
                "goal": "Answer customer queries",
                "subtasks": [
                    {"id": "step_fallback", "description": "Address request in fallback mode", "status": "pending"}
                ],
                "currentStepIndex": 0,
            },
            "global_transitions_count": 1,
        }
