"""运行级中断收口契约(S2c,stream-reliability-push 04 号票)。

``_settle_turn`` 增 ``interrupted`` 旗标后的三条新不变量:
- 终态优先级:运行级中断压倒子任务态 —— 中途停止的计划若按 waiting_approval
  落,会把「用户已停止」谎成「等待审批」(HOT-RESUME 恢复面语义被污染);
- result 帧诚实标注:``interrupted: True`` 且 output 为空(部分态无 finish
  终稿,严禁冒充完成),帧 kind 仍为 result —— 网关「result 帧优雅收口」
  语义不变,否则 SSE 流挂死(断线不回退同类事故);
- 中断不是缺陷:不入坏例池(与熔断/图异常两臂区分,坏例是人审缺陷信号,
  用户主动停止是产品行为)。

缝测试:协作者全桩件,SessionMetric 以密封 PG 真表断言(夹具同
test_settle_turn_seam)。
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

FAKE_TOKENS = 4321


class _InterruptedStubs:
    def __init__(self) -> None:
        self.publish_calls: list[tuple] = []
        self.short_adds: list[tuple] = []
        self.task_saves: list[dict] = []
        self.badcase_calls: list[tuple] = []

    def patch(self, monkeypatch) -> None:
        module = importlib.import_module("engine_py.run_agent")
        stubs = self

        class ShortMemory:
            def __init__(self, thread_id, limit, business_id):
                pass

            async def add_message(self, role, content, cards=None):
                stubs.short_adds.append((role, content, cards))

        class LongMemory:
            def __init__(self, user_id, business_id):
                pass

            async def extract_and_store_fact(self, output, message):
                raise AssertionError("中断轮无终稿,不得触发长期记忆抽取")

        class EpisodicMemory:
            def __init__(self, user_id, business_id):
                pass

            async def add_event(self, summary, score):
                raise AssertionError("中断轮无终稿,不得触发情境记忆写回")

        class TaskMemory:
            def __init__(self, thread_id):
                pass

            async def save_task_state(self, state):
                stubs.task_saves.append(state)

        async def drain(thread_id):
            pass

        def take_total(thread_id):
            return FAKE_TOKENS

        async def badcase(source, **kw):
            stubs.badcase_calls.append((source, kw))

        async def claim(thread_id, business_id, output):
            pass

        async def publish(job_id, kind, payload):
            stubs.publish_calls.append((job_id, kind, payload))

        monkeypatch.setattr(module, "ShortMemory", ShortMemory)
        monkeypatch.setattr(module, "LongMemory", LongMemory)
        monkeypatch.setattr(module, "EpisodicMemory", EpisodicMemory)
        monkeypatch.setattr(module, "TaskMemory", TaskMemory)
        monkeypatch.setattr(module, "drain_llm_call_writes", drain)
        monkeypatch.setattr(module, "take_thread_token_total", take_total)
        monkeypatch.setattr(module, "record_badcase_signal", badcase)
        monkeypatch.setattr(module, "record_claim_mismatch_if_any", claim)
        monkeypatch.setattr(module, "publish_agent_event", publish)
        monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)


def _interrupted_result() -> dict:
    """检查点命中的部分态:计划走到一半,无 finish 终稿(output 缺席),
    已完成的子任务里有一个曾等待审批(被停止打断,未到恢复语义)。"""
    return {
        "thread_id": "t-interrupted",
        "user_id": "CUST-INT",
        "job_id": "job-interrupted",
        "input": "退款+查订单",
        "business_config": {"businessId": "aurora"},
        "task_plan": {
            "goal": "退款与查询",
            "subtasks": [
                {"id": "s1", "status": "completed", "result": {}},
                {"id": "s2", "status": "pending", "result": {"waitingForApproval": True}},
            ],
            "currentStepIndex": 1,
        },
        "loop_count": 3,
        "intents": [{"intent": "refund", "confidence": 0.9}],
    }


def _make_job():
    module = importlib.import_module("engine_py.run_agent")
    return module.AgentJobInput(
        job_id="job-interrupted",
        thread_id="t-interrupted",
        user_id="CUST-INT",
        business_id="aurora",
        message="退款+查订单",
    )


async def _settle(stubs: _InterruptedStubs, result: dict):
    module = importlib.import_module("engine_py.run_agent")
    return await module._settle_turn(
        result,
        job=_make_job(),
        business_id="aurora",
        llm_breaker_fired=False,
        graph_error_fired=False,
        interrupted=True,
        elapsed_latency_ms=88.0,
        saved_guide_context=None,
        saved_cart_context=None,
        saved_order_context=None,
    )


def _seed_thread(pg_factory, thread_id: str = "t-interrupted", user_id: str = "CUST-INT") -> None:
    module = importlib.import_module("engine_py.run_agent")
    asyncio.run(module._ensure_thread(thread_id, user_id, "aurora"))


def _fetch_metric_status(pg_factory, thread_id: str = "t-interrupted") -> str:
    """密封 PG 真表取 resolution_status(模式同 test_settle_turn_seam)。"""
    from sqlalchemy import select

    from engine_py.db import SessionMetric

    async def _fetch():
        async with pg_factory() as session:
            row = (
                (await session.execute(select(SessionMetric).where(SessionMetric.thread_id == thread_id)))
                .scalars()
                .first()
            )
            assert row is not None, "收口必须落 session_metrics 真行"
            return row.resolution_status

    return asyncio.run(_fetch())


@pytest.mark.usefixtures("pg_factory")
def test_interrupted_overrides_subtask_waiting_approval(monkeypatch, pg_factory):
    """中断压倒子任务 waitingForApproval:用户已停止 ≠ 等待审批。"""
    stubs = _InterruptedStubs()
    stubs.patch(monkeypatch)
    _seed_thread(pg_factory)

    asyncio.run(_settle(stubs, _interrupted_result()))

    assert _fetch_metric_status(pg_factory) == "interrupted"
    # 中断不是缺陷,不入坏例池
    assert stubs.badcase_calls == []
    # result 帧诚实标注
    job_id, kind, payload = stubs.publish_calls[0]
    assert (job_id, kind) == ("job-interrupted", "result")
    assert payload["interrupted"] is True
    assert payload["output"] == ""


@pytest.mark.usefixtures("pg_factory")
def test_interrupted_turn_skips_assistant_row_but_saves_task_memory(monkeypatch, pg_factory):
    """无终稿 → 零 assistant 行(时间线无回答,「继续」确定性重派可接力,
    ADR-0013② 同构);任务记忆仍落(已积累的领域上下文跨轮延续)。"""
    stubs = _InterruptedStubs()
    stubs.patch(monkeypatch)
    _seed_thread(pg_factory)

    final = asyncio.run(_settle(stubs, _interrupted_result()))

    assert stubs.short_adds == [], "中断轮不得落 assistant 行冒充回答"
    assert len(stubs.task_saves) == 1, "任务记忆必须落库(上下文延续)"
    assert final["interrupted"] is True


@pytest.mark.usefixtures("pg_factory")
def test_interrupted_thrashing_run_does_not_enter_badcase_pool(monkeypatch, pg_factory):
    """用户掐死打转 run 的部分态(tool_errors≥3 / 转移≥22,取消的典型形态)
    不得按 circuit_breaker 入坏例池 —— 中断不是缺陷,是产品行为。"""
    stubs = _InterruptedStubs()
    stubs.patch(monkeypatch)
    _seed_thread(pg_factory)

    thrashing = {
        **_interrupted_result(),
        "global_transitions_count": 30,
        "tool_errors_count": 5,
    }
    asyncio.run(_settle(stubs, thrashing))

    assert stubs.badcase_calls == [], "被用户掐死打转 run 不入坏例池(非缺陷)"
    assert _fetch_metric_status(pg_factory) == "interrupted", "打转态被掐死仍落 interrupted,不谎成 circuit_breaker"
