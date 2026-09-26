"""validator ⇄ executor 回环语义专项(graph/nodes/validator.py + build_graph.py)。

钉死五件事:
1. 绿灯免校验 —— 无 error 产出 100% 信任放行,零 LLM 开销,步进 +1;
2. 错误输出仲裁 —— LLM YES/NO:标 failed 步进 +1 计错 1,或信任放行零计错;
3. HITL 挂起 —— waitingForApproval 保留现场不步进,零 LLM;
4. 路由判定序 —— 熔断双闸(转移 ≥10 / 计错 ≥3)→ 挂起闸 → admin 驳回认知
   回溯 planner(replanned 标记放行)→ 计划走完/步数封顶 finish → 其余 executor;
5. 计错累计语义 —— validator 每轮产出增量(tool_errors_count 0/1),由图状态
   reducer 累计,跨步达 3 即熔断 finish。

LLM 打桩 get_chat_model(validator 的模块内引用),零真实调用。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

from engine_py.graph.build_graph import route_after_validator
from engine_py.graph.nodes.validator import validator_node


@contextmanager
def _fake_validator_llm(reply: str):
    from engine_py.graph.nodes import validator as vd

    calls: list[str] = []

    class _Model:
        async def ainvoke(self, prompt: str):
            calls.append(prompt)
            return type("Resp", (), {"content": reply})()

    original = vd.get_chat_model
    vd.get_chat_model = lambda: _Model()
    try:
        yield calls
    finally:
        vd.get_chat_model = original


def _plan(index: int, subtasks: list[dict]) -> dict:
    return {"goal": "g", "currentStepIndex": index, "subtasks": subtasks}


# ---------- validator 节点语义 ----------


def test_绿灯免校验_零LLM直接放行():
    plan = _plan(
        0,
        [
            {
                "id": "s0",
                "description": "查询订单",
                "status": "completed",
                "result": {"toolExecuted": "getOrderStatus", "output": {"orderId": "ORD-1", "status": "已发货"}},
            },
            {"id": "s1", "description": "下一步", "status": "pending"},
        ],
    )
    with _fake_validator_llm("NO") as calls:  # 即便模型会判 NO 也不该被问
        result = asyncio.run(validator_node({"task_plan": plan}))

    assert calls == []
    assert result["task_plan"]["currentStepIndex"] == 1
    assert result["task_plan"]["subtasks"][0]["status"] == "completed"
    assert result["tool_errors_count"] == 0


def test_错误输出LLM判NO_标failed步进并计错():
    plan = _plan(
        0,
        [
            {"id": "s0", "description": "退款", "status": "completed", "result": {"error": "工具超时"}},
            {"id": "s1", "description": "下一步", "status": "pending"},
        ],
    )
    with _fake_validator_llm("NO") as calls:
        result = asyncio.run(validator_node({"task_plan": plan}))

    assert len(calls) == 1
    assert result["task_plan"]["subtasks"][0]["status"] == "failed"
    assert result["task_plan"]["currentStepIndex"] == 1
    assert result["tool_errors_count"] == 1


def test_错误输出LLM判YES_信任放行零计错():
    plan = _plan(
        0,
        [
            {"id": "s0", "description": "退款", "status": "completed", "result": {"error": "部分字段缺失"}},
            {"id": "s1", "description": "下一步", "status": "pending"},
        ],
    )
    with _fake_validator_llm("YES") as calls:
        result = asyncio.run(validator_node({"task_plan": plan}))

    assert len(calls) == 1
    assert result["task_plan"]["subtasks"][0]["status"] == "completed"
    assert result["task_plan"]["currentStepIndex"] == 1
    assert result["tool_errors_count"] == 0


def test_审批挂起_保留现场不步进():
    plan = _plan(
        0,
        [
            {
                "id": "s0",
                "description": "退款",
                "status": "pending",
                "result": {"waitingForApproval": True, "approvalId": "apr_1"},
            },
        ],
    )
    with _fake_validator_llm("NO") as calls:
        result = asyncio.run(validator_node({"task_plan": plan}))

    assert calls == []
    assert result["task_plan"]["currentStepIndex"] == 0
    assert result["task_plan"]["subtasks"][0]["status"] == "pending"


# ---------- route_after_validator 路由判定序 ----------


_MID_PLAN = _plan(
    0,
    [
        {"id": "s0", "description": "a", "status": "completed"},
        {"id": "s1", "description": "b", "status": "pending"},
    ],
)


def test_无异常回环继续executor():
    assert route_after_validator({"task_plan": _MID_PLAN}) == "executor"


def test_计错累计达3熔断finish():
    assert route_after_validator({"task_plan": _MID_PLAN, "tool_errors_count": 3}) == "finish"


def test_转移计数达10熔断finish():
    assert route_after_validator({"task_plan": _MID_PLAN, "global_transitions_count": 10}) == "finish"


def test_任一步挂起即finish():
    plan = _plan(
        0,
        [
            {"id": "s0", "description": "a", "status": "pending", "result": {"waitingForApproval": True}},
            {"id": "s1", "description": "b", "status": "pending"},
        ],
    )
    assert route_after_validator({"task_plan": plan}) == "finish"


def test_admin驳回未replan_认知回溯planner():
    plan = _plan(
        0,
        [
            {
                "id": "s0",
                "description": "退款",
                "status": "failed",
                "result": {"rejectedByAdmin": True, "rejectionReason": "金额超限"},
            },
            {"id": "s1", "description": "b", "status": "pending"},
        ],
    )
    assert route_after_validator({"task_plan": plan}) == "planner"


def test_admin驳回已replan标记_放行继续executor():
    plan = _plan(
        0,
        [
            {
                "id": "s0",
                "description": "退款",
                "status": "failed",
                "result": {"rejectedByAdmin": True, "replanned": True},
            },
            {"id": "s1", "description": "b", "status": "pending"},
        ],
    )
    assert route_after_validator({"task_plan": plan}) == "executor"


def test_计划走完finish():
    done = _plan(
        2,
        [
            {"id": "s0", "description": "a", "status": "completed"},
            {"id": "s1", "description": "b", "status": "completed"},
        ],
    )
    assert route_after_validator({"task_plan": done}) == "finish"


def test_步数封顶finish():
    long_plan = _plan(10, [{"id": f"s{i}", "description": "x", "status": "completed"} for i in range(12)])
    assert route_after_validator({"task_plan": long_plan}) == "finish"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])
