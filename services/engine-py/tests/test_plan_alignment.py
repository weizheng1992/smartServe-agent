"""planner 计划后置对齐回归(2026-09-27 立案 planner-plan-intent-alignment)。

钉死三层:
1. 纯函数层 —— align_plan_to_intents 表驱动:意图×计划×预期存活子任务,
   含「买2件 ≠ 下单」资金门正反向、诚实反问步放行、无动词叙事剪(幻觉发明)、
   全剪保护、未登记意图放行。
2. 图层 —— 真实 build_graph,planner LLM 打桩返回事故同款 5 步计划,
   断言 executor 只见对齐后子任务、无 checkoutCart/confirmOrder。
3. 快轨层 —— 单 cart_manage 销量榜词加购形态零 LLM 规划(确定性单步
   CartSkill),事故 5 步自由发挥不再发生。
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from engine_py.graph import build_graph as bg_fn
from engine_py.graph.nodes import executor as executor_mod
from engine_py.graph.nodes import finish as finish_mod
from engine_py.graph.nodes import planner as planner_mod
from engine_py.graph.plan_alignment import align_plan_to_intents
from engine_py.graph.state import AgentState

BG = sys.modules["engine_py.graph.build_graph"]


def _plan(*descriptions: str) -> dict:
    return {
        "goal": "test",
        "subtasks": [
            {"id": f"s{i}", "description": d, "status": "pending"} for i, d in enumerate(descriptions)
        ],
        "currentStepIndex": 0,
    }


_CART_INTENTS = [{"intent": "cart_manage", "confidence": 0.9}]


# ---------- 1. 纯函数层 ----------


def test事故同款五步计划收敛到加购单步():
    """实弹:排行/确认订单/改量/结算四步越界剪,只留 addToCart。"""
    plan = _plan(
        "Call queryProductRanking with rankingMetric volume to fetch real sales ranking",
        "Call addToCart to add the best-selling pants quantity 2",
        "Call confirmOrder to confirm the order",
        "Call modifyCart to set quantity 2",
        "Call checkoutCart to place a real order",
    )
    aligned, pruned = align_plan_to_intents(_CART_INTENTS, plan, "把销量最好的裤子放到购物车，买2件")
    assert [s["id"] for s in aligned["subtasks"]] == ["s1"]
    assert len(pruned) == 4


def test买2件不是下单资金门反向():
    """「买2件」是数量槽位:checkoutCart 即使被 LLM 排进计划也必须剪。"""
    plan = _plan("Call addToCart to add pants", "Call checkoutCart to place a real order")
    aligned, pruned = align_plan_to_intents(_CART_INTENTS, plan, "把裤子加入购物车，买2件")
    assert [s["id"] for s in aligned["subtasks"]] == ["s0"]
    assert "checkoutCart" in pruned[0]


def test当前输入明说下单则结算步存活():
    """资金门正向:当前输入命中下单词族,checkoutCart 放行(真实下单请求不受伤)。"""
    plan = _plan("Call addToCart to add pants", "Call checkoutCart to place a real order")
    aligned, _ = align_plan_to_intents(_CART_INTENTS, plan, "把裤子加入购物车然后结算下单")
    assert [s["id"] for s in aligned["subtasks"]] == ["s0", "s1"]


def test诚实反问步放行():
    plan = _plan("Call listUserOrders to fetch recent orders", "Ask the customer which order to refund")
    aligned, pruned = align_plan_to_intents(
        [{"intent": "refund", "confidence": 0.9}], plan, "我要退货"
    )
    assert [s["id"] for s in aligned["subtasks"]] == ["s0", "s1"]
    assert pruned == []


def test无动词叙事步按幻觉发明剪():
    """09-13 深规划幻觉叙事事故同源:无 Call/Execute/ask 的纯叙事步不得进 executor。"""
    plan = _plan("Call processRefund for order ORD-123", "The refund will be processed successfully soon")
    aligned, pruned = align_plan_to_intents(
        [{"intent": "refund", "confidence": 0.9}], plan, "退了订单ORD-123"
    )
    assert [s["id"] for s in aligned["subtasks"]] == ["s0"]
    assert len(pruned) == 1


def test全剪保护回落单步诚实计划():
    plan = _plan("Call confirmOrder", "Call checkoutCart")
    aligned, pruned = align_plan_to_intents(_CART_INTENTS, plan, "加购裤子")
    assert len(pruned) == 2
    assert len(aligned["subtasks"]) == 1
    assert aligned["subtasks"][0]["id"] == "step_aligned_fallback"
    assert "cart_manage" in aligned["subtasks"][0]["description"]


def test未登记意图整体放行():
    """对齐闸只对已登记白名单族生效:全部检出意图无白名单 → 原样放行。"""
    plan = _plan("Some narrative step without verbs")
    aligned, pruned = align_plan_to_intents(
        [{"intent": "human_escalation", "confidence": 0.9}], plan, "转人工"
    )
    assert pruned == []
    assert len(aligned["subtasks"]) == 1


def test截断兜底per_intent计划不过闸(monkeypatch):
    """JSON 解析失败的确定性兜底计划(planner 亲造、按检出意图一一对应)
    不得被对齐闸误剪 —— 闸只管 LLM 自由输出(2026-09-27 合同测试逮住的
    误剪缺陷:refund+order_status 两步被剪成 step_aligned_fallback 单步)。"""

    class _BrokenModel:
        class _Resp:
            content = "模型截断的非JSON碎片..."

        async def ainvoke(self, _prompt):
            return self._Resp()

    monkeypatch.setattr(planner_mod, "planner_llm", lambda: _BrokenModel())
    state: AgentState = {
        "input": "帮我处理下",
        "thread_id": "dbg_alignment_thread",
        "business_id": "aurora",
        "intents": [{"intent": "refund"}, {"intent": "order_status"}],
    }
    result = asyncio.run(planner_mod.planner_node(state))
    subtasks = (result.get("task_plan") or {}).get("subtasks") or []
    assert [s["description"] for s in subtasks] == [
        "Handle refund process",
        "Handle order_status process",
    ]


def test技能步按意图族放行():
    plan = _plan("Execute CartSkill for input: 加购裤子", "Execute OrderRefundSkill for input: 退款")
    aligned, pruned = align_plan_to_intents(_CART_INTENTS, plan, "加购裤子")
    assert [s["id"] for s in aligned["subtasks"]] == ["s0"]
    assert len(pruned) == 1


def test复合购物意图白名单并集():
    """guide+cart 复合:两意图白名单取并集,排行步(导购面)存活。"""
    plan = _plan(
        "Call queryProductRanking with rankingMetric volume",
        "Call searchProducts with query 裤子",
        "Call addToCart to add the first pant",
        "Call checkoutCart to place a real order",
    )
    aligned, pruned = align_plan_to_intents(
        [{"intent": "shopping_guide"}, {"intent": "cart_manage"}], plan, "推荐裤子加购,不要结算"
    )
    assert [s["id"] for s in aligned["subtasks"]] == ["s0", "s1", "s2"]
    assert len(pruned) == 1


# ---------- 2. 图层:真实 build_graph + 打桩 LLM ----------


class _PlannerFakeModel:
    """返回事故同款 5 步 JSON 的假规划模型。"""

    class _Resp:
        content = (
            '{"goal": "Add best-selling pants to cart and purchase two", "subtasks": ['
            '{"id": "queryProductRanking_1", "description": "Call queryProductRanking with '
            'rankingMetric volume to fetch real sales ranking"},'
            '{"id": "addToCart_1", "description": "Call addToCart to add the best-selling pants quantity 2"},'
            '{"id": "confirmOrder_1", "description": "Call confirmOrder to confirm the order"},'
            '{"id": "modifyCart_1", "description": "Call modifyCart to set quantity 2"},'
            '{"id": "checkoutCart_1", "description": "Call checkoutCart to place a real order"}]}'
        )

    async def ainvoke(self, _prompt):
        return self._Resp()


class _FinishFakeModel:
    class _Resp:
        content = "已按您的要求处理加购。"

    async def ainvoke(self, _prompt):
        return self._Resp()


async def _green_step_stub(state):
    """镜像 step_execution_engine 返回形状:恒绿 +1 转移,index 由 validator 推进。"""
    plan = dict(state.get("task_plan") or {})
    subtasks = [dict(st) for st in plan.get("subtasks") or []]
    idx = plan.get("currentStepIndex", 0)
    if 0 <= idx < len(subtasks):
        subtasks[idx] = {
            **subtasks[idx],
            "status": "completed",
            "result": {"output": "ok", "success": True, "error": None},
        }
    return {
        "taskPlan": {**plan, "subtasks": subtasks, "currentStepIndex": idx},
        "globalTransitionsCount": 1,
    }


async def _triage_stub(_state):
    return {"intents": [{"intent": "cart_manage", "confidence": 0.95}]}


def test图层深规划事故计划被对齐后执行(monkeypatch):
    """真实图回路:planner LLM 打桩返回事故 5 步 → executor 只见对齐后子任务。
    输入刻意不含榜词(事故原句会被 D4 快轨截走 —— 那条路另有专项断言),
    走深规划路径才能测对齐闸。"""
    executed: list[str] = []

    async def _tracking_step(state):
        plan = state.get("task_plan") or {}
        subtasks = plan.get("subtasks") or []
        idx = plan.get("currentStepIndex", 0)
        if 0 <= idx < len(subtasks):
            executed.append(subtasks[idx].get("description") or "")
        return await _green_step_stub(state)

    monkeypatch.setattr(planner_mod, "planner_llm", lambda: _PlannerFakeModel())
    monkeypatch.setattr(executor_mod, "execute_step", _tracking_step)
    monkeypatch.setattr(finish_mod, "get_chat_model", lambda: _FinishFakeModel())
    monkeypatch.setattr(BG, "triage_node", _triage_stub)

    state: AgentState = {
        "input": "把这条裤子加入购物车，买2件",
        "thread_id": "dbg_alignment_thread",
        "business_id": "aurora",
        "global_transitions_count": 0,
        "tool_errors_count": 0,
    }
    result = asyncio.run(bg_fn().ainvoke(state))

    assert executed, "对齐后计划必须仍有可执行步"
    assert all("checkoutCart" not in d and "confirmOrder" not in d for d in executed), (
        f"越界步不得进 executor: {executed}"
    )
    assert all("addToCart" in d for d in executed), f"只应执行白名单内加购步: {executed}"
    assert "熔断" not in str(result.get("output") or "")


def test图层事故原句走快轨单步执行(monkeypatch):
    """事故原句(含榜词)在真实图里被 D4 快轨截走:单步 CartSkill,零深规划。"""
    llm_calls = {"n": 0}

    def _counting_llm():
        llm_calls["n"] += 1
        return _PlannerFakeModel()

    executed: list[str] = []

    async def _tracking_step(state):
        plan = state.get("task_plan") or {}
        subtasks = plan.get("subtasks") or []
        idx = plan.get("currentStepIndex", 0)
        if 0 <= idx < len(subtasks):
            executed.append(subtasks[idx].get("description") or "")
        return await _green_step_stub(state)

    monkeypatch.setattr(planner_mod, "planner_llm", _counting_llm)
    monkeypatch.setattr(executor_mod, "execute_step", _tracking_step)
    monkeypatch.setattr(finish_mod, "get_chat_model", lambda: _FinishFakeModel())
    monkeypatch.setattr(BG, "triage_node", _triage_stub)

    state: AgentState = {
        "input": "把销量最好的裤子放到购物车，买2件",
        "thread_id": "dbg_alignment_thread",
        "business_id": "aurora",
        "global_transitions_count": 0,
        "tool_errors_count": 0,
    }
    asyncio.run(bg_fn().ainvoke(state))

    assert llm_calls["n"] == 0, "事故原句必须零 LLM 规划(快轨直达)"
    assert len(executed) == 1 and "CartSkill" in executed[0], f"应单步 CartSkill: {executed}"


# ---------- 3. 快轨层:榜词加购零 LLM 规划 ----------


def test榜词加购快轨零LLM规划(monkeypatch):
    """单 cart_manage + 销量榜词:确定性单步 CartSkill,严禁坠入 LLM 深规划。"""
    llm_calls = {"n": 0}

    def _counting_llm():
        llm_calls["n"] += 1
        return _PlannerFakeModel()

    monkeypatch.setattr(planner_mod, "planner_llm", _counting_llm)

    state: AgentState = {
        "input": "把销量最好的裤子放到购物车，买2件",
        "thread_id": "dbg_alignment_thread",
        "business_id": "aurora",
        "intents": [{"intent": "cart_manage", "confidence": 0.95}],
    }
    result = asyncio.run(planner_mod.planner_node(state))

    assert llm_calls["n"] == 0, "榜词加购形态必须零 LLM 规划"
    subtasks = (result.get("task_plan") or {}).get("subtasks") or []
    assert len(subtasks) == 1
    assert "CartSkill" in (subtasks[0].get("description") or "")


def test榜词加购伴生metric半不否决快轨(monkeypatch):
    """09-27 实弹取证:triage 对「销量最好」必拆出 metric_query 伴生半,
    旧 D4 条件被 not has_metric_intent 否决 → 事故原句坠深规划。
    修后:cart_manage 在场 + 榜词命中即为判据,metric 半不拦(全店榜同样
    答不了品类最优,CartSkill 诚实反问是并集正解)。"""

    class _SpyModel:
        async def ainvoke(self, _prompt):
            raise AssertionError("榜词加购+metric伴生形态必须零 LLM 规划")

    monkeypatch.setattr(planner_mod, "planner_llm", lambda: _SpyModel())

    state: AgentState = {
        "input": "把销量最好的裤子放到购物车，买2件",
        "thread_id": "dbg_alignment_thread",
        "business_id": "aurora",
        "intents": [
            {"intent": "cart_manage", "confidence": 0.9},
            {"intent": "metric_query", "confidence": 0.55},
        ],
    }
    result = asyncio.run(planner_mod.planner_node(state))
    subtasks = (result.get("task_plan") or {}).get("subtasks") or []
    assert len(subtasks) == 1 and "CartSkill" in (subtasks[0].get("description") or "")


def test明说下单不进榜词快轨仍走规划(monkeypatch):
    """当前输入含下单词:不劫持(真实下单请求按规则 8 走规划/资金路径)。"""
    llm_calls = {"n": 0}

    def _counting_llm():
        llm_calls["n"] += 1
        return _PlannerFakeModel()

    monkeypatch.setattr(planner_mod, "planner_llm", _counting_llm)

    state: AgentState = {
        "input": "把裤子加入购物车，然后结算下单",
        "thread_id": "dbg_alignment_thread",
        "business_id": "aurora",
        "intents": [{"intent": "cart_manage", "confidence": 0.95}],
    }
    asyncio.run(planner_mod.planner_node(state))
    assert llm_calls["n"] == 1, "下单词在场不得被榜词快轨劫持"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """除显式打桩外严禁真实 LLM/DB 出手(纯本地回路)。"""
    monkeypatch.setenv("AI_BASE_URL", "http://127.0.0.1:1")
