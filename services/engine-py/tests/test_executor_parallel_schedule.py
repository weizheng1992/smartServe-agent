"""执行器并行调度专册(2026-10-01 夜审补缺,此前零直接测试)。

钉死 execute_step 的调度面(不动工具执行本体,`_execute_single_step_core`
与快速路匹配器一律 monkeypatch):
1. 独立子任务物理并行 —— 连续可匹配步骤聚成 candidate_indices 一次
   asyncio.gather,以「同时活跃协程数峰值」实证真并发(非顺序await);
2. 技能链强制串行护栏(2026-09-13 实弹)—— 当前步或后继步命中技能
   (guide 写候选 → cart 读候选是有状态 SOP 链)即 break,绝不 gather;
3. 并行聚簇边界 —— 非匹配步骤 / 转人工步骤截断聚簇,不拖入并行;
4. 并行分支的上下文 merge 透传,串行分支不透传。

全程无 job_id(不发事件)、short_memory 非空(不触 ShortMemory/DB)。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.graph.nodes import step_execution_engine as see


@pytest.fixture()
def schedule_recorder(monkeypatch):
    """桩掉单步执行核与快速路匹配器;记录 idx 调用序与同时活跃峰值。"""
    calls: list[int] = []

    async def _fake_core(state, plan, idx, allowed_tools, short_memory, history_context):
        calls.append(idx)
        holder = state["_recorder"]
        holder["active"] += 1
        holder["peak"] = max(holder["peak"], holder["active"])
        await asyncio.sleep(0.01)  # 让出事件循环:若被顺序 await 则峰值恒 1
        holder["active"] -= 1
        step = {**plan["subtasks"][idx], "status": "completed"}
        return {"updatedStep": step, "toolErrorsCount": 0}

    def _fake_match(desc, user_input, allowed_tools, short_memory, cart_last_added=None):
        d = (desc or "").strip()
        tool = {
            "查订单": "getOrderStatus",
            "查物流": "getOrderStatus",
            "推荐商品": "skill_shopping_guide",
            "加购物车": "skill_cart_manage",
        }.get(d)
        if tool:
            return {"toolName": tool}
        if "转人工" in d or "escalat" in d.lower():
            # 匹配成立,靠调度面 is_escalation 语义闸截断(非匹配缺失截断)
            return {"toolName": "getOrderStatus"}
        return None

    monkeypatch.setattr(see, "_execute_single_step_core", _fake_core)
    monkeypatch.setattr(see, "try_match_executor_fast_path", _fake_match)
    return calls


def _state(descriptions: list[str]) -> dict:
    return {
        "input": "帮我处理一下",
        "thread_id": "t-par-1",
        "short_memory": [{"role": "user", "content": "帮我处理一下"}],
        "_recorder": {"active": 0, "peak": 0},
        "task_plan": {
            "currentStepIndex": 0,
            "subtasks": [{"id": f"s{i}", "description": d, "status": "pending"} for i, d in enumerate(descriptions)],
        },
    }


def _peak(state: dict) -> int:
    return state["_recorder"]["peak"]


def test_独立子任务物理并行(schedule_recorder):
    state = _state(["查订单", "查物流"])
    out = asyncio.run(see.execute_step(state))
    assert schedule_recorder == [0, 1]
    assert _peak(state) == 2, "两步必须同时活跃(gather 真并发),顺序 await 峰值恒 1"
    assert [st["status"] for st in out["taskPlan"]["subtasks"]] == ["completed", "completed"]
    assert out["globalTransitionsCount"] == 1 and out["toolErrorsCount"] == 0


def test_当前技能步截断聚簇(schedule_recorder):
    """当前步是技能(guide)→ 聚簇立即截断,单步串行执行 —— guide 写候选 →
    cart 读候选是有状态 SOP 链,曾被 gather 同一 state 拷贝并行打穿。"""
    state = _state(["推荐商品", "加购物车", "查订单"])
    out = asyncio.run(see.execute_step(state))
    assert schedule_recorder == [0], "技能链只串行执行当前步"
    assert _peak(state) == 1
    assert out["taskPlan"]["subtasks"][0]["status"] == "completed"
    assert out["taskPlan"]["subtasks"][1]["status"] == "pending", "后继步骤不得被并行消费"
    assert out.get("guideContext") is None and out.get("cartContext") is None, "串行分支无上下文可 merge"


def test_后继技能步截断聚簇(schedule_recorder):
    """当前步是普通工具、后继步是技能 → 同样截断(护栏看双向)。"""
    state = _state(["查订单", "推荐商品"])
    asyncio.run(see.execute_step(state))
    assert schedule_recorder == [0]
    assert _peak(state) == 1


def test_非匹配步骤截断聚簇(schedule_recorder):
    """连续匹配段聚簇并行,首个不匹配步骤截断 —— 只 gather [0,1]。"""
    state = _state(["查订单", "查物流", "做点别的"])
    out = asyncio.run(see.execute_step(state))
    assert schedule_recorder == [0, 1]
    assert _peak(state) == 2
    assert out["taskPlan"]["subtasks"][2]["status"] == "pending"


def test_转人工步骤不拖入并行(schedule_recorder):
    """匹配成立但带转人工语义的步骤不得并入聚簇(升级是终局语义,须单独走)。"""
    state = _state(["查订单", "转人工 escalation"])
    asyncio.run(see.execute_step(state))
    assert schedule_recorder == [0]
    assert _peak(state) == 1


def test_并行分支上下文merge透传(schedule_recorder, monkeypatch):
    """任一并行步产出 guideContext/cartContext → 输出层 merge 透传。"""
    base_core = see._execute_single_step_core

    async def _core_with_ctx(state, plan, idx, allowed_tools, short_memory, history_context):
        res = await base_core(state, plan, idx, allowed_tools, short_memory, history_context)
        if idx == 1:
            res["guideContext"] = {"candidates": ["SPU-1"]}
        if idx == 0:
            res["cartContext"] = {"addedThisTurn": ["SPU-0"]}
        return res

    monkeypatch.setattr(see, "_execute_single_step_core", _core_with_ctx)
    out = asyncio.run(see.execute_step(_state(["查订单", "查物流"])))
    assert out["guideContext"] == {"candidates": ["SPU-1"]}
    assert out["cartContext"] == {"addedThisTurn": ["SPU-0"]}
