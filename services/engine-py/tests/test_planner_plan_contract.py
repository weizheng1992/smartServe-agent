"""planner 计划契约专项(graph/nodes/planner.py)。

钉死四件事:
1. 计划形状契约 —— 快轨与深规划产出的 task_plan 一律
   {goal, subtasks, currentStepIndex: 0};深规划归一化把 LLM 自由发挥的
   多余键(dependencies/toolName 等)剥到 {id, description, status: pending};
2. 资金纪律 —— 退款/退货无显式订单号严禁 step_fast_refund 快轨直达,
   降级 LLM 深规划由其向用户澄清(2026-09-05 历史回填双退款事故);
3. 部分失败降级 —— LLM 截断/脏输出落 per-intent 兜底单步计划,节点异常落
   step_fallback,规划输出类失败不炸会话;熔断(CircuitBreakerOpenError)
   上抛 job 级另论;
4. 确定性快轨零 LLM —— general_query 旁路/metric_query 排行/显式单号复合
   订单动作均不消耗模型调用。

全程打桩 get_chat_model(planner_llm 的模块内引用),零 LLM 调用。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest

from engine_py.graph.nodes.planner import planner_node
from engine_py.llm import CircuitBreakerOpenError


@contextmanager
def _fake_planner_llm(content: str | None = None, *, exc: Exception | None = None):
    """打桩 planner.get_chat_model,返回 prompt 收集列表供零 LLM 断言。"""
    from engine_py.graph.nodes import planner as pl

    calls: list[str] = []

    class _Bound:
        async def ainvoke(self, prompt: str):
            calls.append(prompt)
            if exc is not None:
                raise exc
            return type("Resp", (), {"content": content})()

    class _Model:
        def bind(self, **_kwargs) -> _Bound:
            return _Bound()

    original = pl.get_chat_model
    pl.get_chat_model = lambda: _Model()
    try:
        yield calls
    finally:
        pl.get_chat_model = original


def _state(**kwargs) -> dict:
    base = {"intents": [], "input": "", "short_memory": [{"role": "user", "content": "你好"}]}
    base.update(kwargs)
    return base


# ---------- 确定性快轨:计划形状 + 零 LLM ----------


def test_general_query旁路_计划形状契约与零LLM():
    with _fake_planner_llm("must not be called") as calls:
        result = asyncio.run(planner_node(_state(intents=[{"intent": "general_query"}])))

    plan = result["task_plan"]
    assert plan["currentStepIndex"] == 0
    assert plan["subtasks"] == [
        {"id": "respond_general", "description": "Present general query response to user", "status": "pending"}
    ]
    assert calls == []


def test_metric_query快轨_利润词解析gross_profit():
    with _fake_planner_llm("must not be called") as calls:
        result = asyncio.run(planner_node(_state(intents=[{"intent": "metric_query"}], input="最赚钱的商品排行")))

    plan = result["task_plan"]
    assert plan["goal"] == "Fetch real product ranking by metric"
    (step,) = plan["subtasks"]
    assert step["id"] == "step_fast_ranking_0"
    assert "gross_profit" in step["description"]
    assert step["status"] == "pending"
    assert calls == []


def test_metric_query快轨_销量词解析volume():
    with _fake_planner_llm("must not be called") as calls:
        result = asyncio.run(planner_node(_state(intents=[{"intent": "metric_query"}], input="销量最高的商品")))

    (step,) = result["task_plan"]["subtasks"]
    assert "volume" in step["description"]
    assert calls == []


def test_显式订单号复合订单意图_快轨多子任务形状():
    with _fake_planner_llm("must not be called") as calls:
        result = asyncio.run(
            planner_node(
                _state(
                    intents=[{"intent": "order_status"}, {"intent": "refund"}],
                    input="查一下ORD-98712,顺便退款",
                )
            )
        )

    assert calls == []
    plan = result["task_plan"]
    assert plan["goal"] == "Execute multiple subtasks for order ORD-98712"
    assert [st["id"] for st in plan["subtasks"]] == ["step_fast_status_0", "step_fast_refund_1"]
    assert all(st["status"] == "pending" for st in plan["subtasks"])
    assert result["global_transitions_count"] == 1


# ---------- 资金纪律:无显式单号降级深规划 ----------


def test_退款无显式订单号_降级深规划不快轨():
    fenced = (
        "```json\n"
        '{"goal": "Clarify refund target", "subtasks": ['
        '{"id": "ask_order", "description": "Ask customer which order to refund", '
        '"dependencies": [], "toolName": "processRefund"}]}\n'
        "```"
    )
    with _fake_planner_llm(fenced) as calls:
        result = asyncio.run(
            planner_node(
                _state(intents=[{"intent": "refund", "missingSlots": ["orderId"]}], input="我要退款")
            )
        )

    assert len(calls) == 1  # 走了 LLM 深规划,而非 step_fast_refund 快轨
    plan = result["task_plan"]
    assert plan["goal"] == "Clarify refund target"
    assert plan["currentStepIndex"] == 0
    # LLM 多余键(dependencies/toolName)被归一化剥离,status 统一 pending
    assert plan["subtasks"] == [
        {"id": "ask_order", "description": "Ask customer which order to refund", "status": "pending"}
    ]


# ---------- 部分失败降级 ----------


def test_截断或脏输出落per_intent兜底单步计划():
    with _fake_planner_llm("模型截断的非JSON碎片..."):
        result = asyncio.run(
            planner_node(
                _state(intents=[{"intent": "refund"}, {"intent": "order_status"}], input="帮我处理下")
            )
        )

    plan = result["task_plan"]
    assert plan["goal"] == "Address customer request"
    assert plan["subtasks"] == [
        {"id": "step_0", "description": "Handle refund process", "status": "pending"},
        {"id": "step_1", "description": "Handle order_status process", "status": "pending"},
    ]
    assert plan["currentStepIndex"] == 0


def test_节点异常落step_fallback计划():
    with _fake_planner_llm(exc=RuntimeError("boom")):
        result = asyncio.run(planner_node(_state(intents=[{"intent": "refund"}], input="我要退款")))

    plan = result["task_plan"]
    assert plan["goal"] == "Answer customer queries"
    assert plan["subtasks"] == [
        {"id": "step_fallback", "description": "Address request in fallback mode", "status": "pending"}
    ]
    assert plan["currentStepIndex"] == 0


def test_熔断异常上抛job级不吞():
    status = {"state": "open", "nextAttemptInMs": 30000}
    with _fake_planner_llm(exc=CircuitBreakerOpenError(status)), pytest.raises(CircuitBreakerOpenError):
        asyncio.run(planner_node(_state(intents=[{"intent": "refund"}], input="我要退款")))


if __name__ == "__main__":
    pytest.main([__file__])
