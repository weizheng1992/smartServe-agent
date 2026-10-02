"""收口内部缝(_settle_turn)契约钉死(ADR-0007,提交②穿缝测试)。

图后持久化段已内聚为 run_agent 的私有缝 ``_settle_turn`` —— 遥测落盘 →
订单宣称反幻觉闸 → 卡片合成 → 记忆回写 → 任务记忆 → result 事件,顺序即
契约。本文件直接穿该内部缝(不经图、不经 LLM):协作者全部以桩件替换,
SessionMetric 以密封 PG 真表断言(夹具同 test_deterministic_fallback_wiring)。

钉死的三类回归面:
- 身份:降级臂结果里没有 business_config,收口必须吃 run_agent 显式递入的
  权威租户(旧 Temporal activity 手抄收口正是死在这一类接线上);
- 顺序:drain → 计量 → 宣称校验 → 记忆 → 任务记忆 → result 事件;
- 交付不阻断:任何一段持久化失败都不改变返回值的完整性(各段自吞错)。
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

FAKE_TOKENS = 4321


class _SettleStubs:
    """收口协作者桩件集:记录调用与事件序,供逐测试断言。"""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.badcase_calls: list[tuple] = []
        self.claim_calls: list[tuple] = []
        self.publish_calls: list[tuple] = []
        self.short_adds: list[tuple] = []
        self.episodic_adds: list[tuple] = []
        self.long_facts: list[tuple] = []
        self.task_saves: list[dict] = []
        self.constructed: list[tuple] = []

    def patch(self, monkeypatch) -> None:
        module = importlib.import_module("engine_py.run_agent")
        stubs = self

        class ShortMemory:
            def __init__(self, thread_id, limit, business_id):
                stubs.constructed.append(("short", thread_id, limit, business_id))

            async def add_message(self, role, content, cards=None):
                stubs.short_adds.append((role, content, cards))
                stubs.log.append("assistant_row")

        class LongMemory:
            def __init__(self, user_id, business_id):
                stubs.constructed.append(("long", user_id, business_id))

            async def extract_and_store_fact(self, output, message):
                stubs.long_facts.append((output, message))
                stubs.log.append("long_fact")

        class EpisodicMemory:
            def __init__(self, user_id, business_id):
                stubs.constructed.append(("episodic", user_id, business_id))

            async def add_event(self, summary, score):
                stubs.episodic_adds.append((summary, score))
                stubs.log.append("episodic_event")

        class TaskMemory:
            def __init__(self, thread_id):
                stubs.constructed.append(("task", thread_id))

            async def save_task_state(self, state):
                stubs.task_saves.append(state)
                stubs.log.append("task_memory")

        async def drain(thread_id):
            stubs.log.append("drain_tokens")

        def take_total(thread_id):
            stubs.log.append("take_total")
            return FAKE_TOKENS

        async def badcase(source, **kw):
            stubs.badcase_calls.append((source, kw))
            stubs.log.append("badcase_signal")

        async def claim(thread_id, business_id, output):
            stubs.claim_calls.append((thread_id, business_id, output))
            stubs.log.append("claim_check")

        async def publish(job_id, kind, payload):
            stubs.publish_calls.append((job_id, kind, payload))
            stubs.log.append("publish_result")

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


def _happy_result() -> dict:
    return {
        "thread_id": "t-settle-seam",
        "user_id": "CUST-SEAM",
        "job_id": "job-settle-seam",
        "input": "查订单",
        "business_config": {"businessId": "aurora"},
        "output": "您的订单已发出,预计三天内送达。",
        "task_plan": {
            "goal": "订单查询",
            "subtasks": [{"id": "s1", "status": "completed", "result": {}}],
            "currentStepIndex": 1,
        },
        "loop_count": 5,
        "intents": [],
    }


def _make_job(thread_id: str = "t-settle-seam", business_id: str = "aurora"):
    module = importlib.import_module("engine_py.run_agent")
    return module.AgentJobInput(
        job_id="job-settle-seam",
        thread_id=thread_id,
        user_id="CUST-SEAM",
        business_id=business_id,
        message="查订单",
    )


async def _settle(stubs: _SettleStubs, result: dict, **overrides):
    module = importlib.import_module("engine_py.run_agent")
    kwargs = {
        "job": overrides.pop("job", _make_job()),
        "business_id": overrides.pop("business_id", "aurora"),
        "llm_breaker_fired": overrides.pop("llm_breaker_fired", False),
        "graph_error_fired": overrides.pop("graph_error_fired", False),
        "elapsed_latency_ms": overrides.pop("elapsed_latency_ms", 12.5),
        "saved_guide_context": overrides.pop("saved_guide_context", None),
        "saved_cart_context": overrides.pop("saved_cart_context", None),
        "saved_order_context": overrides.pop("saved_order_context", None),
    }
    assert not overrides, f"未知覆写参数: {overrides}"
    return await module._settle_turn(result, **kwargs)


async def _fetch_metric(pg_factory, thread_id: str) -> dict:
    from sqlalchemy import select

    from engine_py.db import SessionMetric

    async with pg_factory() as session:
        row = (
            (await session.execute(select(SessionMetric).where(SessionMetric.thread_id == thread_id)))
            .scalars()
            .first()
        )
        assert row is not None, "收口必须落 session_metrics 真行"
        return {
            "resolution_status": row.resolution_status,
            "business_id": row.business_id,
            "total_tokens": row.total_tokens,
            "calculated_cost_usd": row.calculated_cost_usd,
            "node_transitions_count": row.node_transitions_count,
            "global_transitions_count": row.global_transitions_count,
            "tool_errors_count": row.tool_errors_count,
        }


def _seed_thread(pg_factory, thread_id: str = "t-settle-seam", user_id: str = "CUST-SEAM") -> None:
    """session_metrics.thread_id 外键指向 threads:收口前先落线程行。

    生产路径由 run_agent 预装配段的 _ensure_thread 负责;缝测试直接复用
    同一生产助手,绕过它不重隐装配语义。
    """
    module = importlib.import_module("engine_py.run_agent")
    asyncio.run(module._ensure_thread(thread_id, user_id, "aurora"))


@pytest.mark.usefixtures("pg_factory")
def test_happy_turn_settles_full_chain_in_order(monkeypatch, pg_factory):
    stubs = _SettleStubs()
    stubs.patch(monkeypatch)

    _seed_thread(pg_factory)
    final = asyncio.run(_settle(stubs, _happy_result()))

    # 顺序即契约:token 收口 → 计量 → 宣称校验 → 三路记忆 → 任务记忆 → result 事件
    assert stubs.log == [
        "drain_tokens",
        "take_total",
        "claim_check",
        "assistant_row",
        "episodic_event",
        "long_fact",
        "task_memory",
        "publish_result",
    ]
    # 快乐轮无降级旗标,坏例信号不入池
    assert stubs.badcase_calls == []

    # 记忆回写:assistant 行拿到与交付一致的卡片;长程事实吃本轮输入
    role, content, cards = stubs.short_adds[0]
    assert (role, content) == ("assistant", "您的订单已发出,预计三天内送达。")
    assert cards == final["cards"]
    assert stubs.long_facts[0][1] == "查订单"

    # 任务记忆:图终态计划 + 领域上下文(None 回落显式 None,不凭空造字典)
    saved = stubs.task_saves[0]
    assert saved["goal"] == "订单查询"
    assert "guideContext" in saved and "cartContext" in saved and "orderContext" in saved

    # result 事件与返回值同对象交付;TS camelCase 序列化生效
    job_id, kind, payload = stubs.publish_calls[0]
    assert (job_id, kind) == ("job-settle-seam", "result")
    assert payload is final
    assert final["taskPlan"]["goal"] == "订单查询"
    assert final["output"] == "您的订单已发出,预计三天内送达。"


@pytest.mark.usefixtures("pg_factory")
def test_happy_turn_persists_real_session_metric(monkeypatch, pg_factory):
    # 每用例独立 thread:密封 PG 会话级共享,同表断言按 thread 隔离防串行污染
    tid = "t-seam-metric"
    stubs = _SettleStubs()
    stubs.patch(monkeypatch)
    _seed_thread(pg_factory, thread_id=tid)

    asyncio.run(_settle(stubs, _happy_result(), job=_make_job(thread_id=tid)))

    row = asyncio.run(_fetch_metric(pg_factory, tid))
    assert row["resolution_status"] == "resolved_auto"
    assert row["business_id"] == "aurora"
    assert row["total_tokens"] == FAKE_TOKENS
    assert abs(row["calculated_cost_usd"] - FAKE_TOKENS / 1_000_000 * 0.15) < 1e-9
    assert row["node_transitions_count"] == 5
    assert row["global_transitions_count"] == 0
    assert row["tool_errors_count"] == 0


@pytest.mark.usefixtures("pg_factory")
@pytest.mark.parametrize(
    ("flag", "expected_status", "note_fragment"),
    [
        ("llm_breaker_fired", "llm_circuit_breaker", "上游 LLM 熔断"),
        ("graph_error_fired", "graph_error_degraded", "图执行未捕获异常"),
    ],
    ids=["llm_breaker", "graph_error"],
)
def test_degraded_arms_settle_with_explicit_tenant(
    monkeypatch, pg_factory, flag, expected_status, note_fragment
):
    """降级臂结果没有 business_config:收口必须吃显式递入的权威租户。

    旧 Temporal activity 手抄收口正是死在这一类接线上(ADR-0007 退役证据),
    本用例把「降级轮身份不失真」钉死在缝上。
    """
    tid = f"t-seam-{flag.removesuffix('_fired')}"
    stubs = _SettleStubs()
    stubs.patch(monkeypatch)

    _seed_thread(pg_factory, thread_id=tid)

    degraded = {
        "output": "非常抱歉,智能服务当前遇到上游模型波动,暂时无法处理您的请求。",
        "task_plan": {"goal": "", "subtasks": [], "currentStepIndex": 0},
        "loop_count": 0,
        "global_transitions_count": 0,
        "tool_errors_count": 0,
    }

    final = asyncio.run(_settle(stubs, degraded, job=_make_job(thread_id=tid), **{flag: True}))

    (source, kw) = stubs.badcase_calls[0]
    from engine_py.badcase.pool import SOURCE_CIRCUIT_BREAKER

    assert source == SOURCE_CIRCUIT_BREAKER
    assert kw["business_id"] == "aurora", "坏例信号租户必须来自收口实参,严禁依赖图终态"
    assert kw["conversation_ref"] == f"thread:{tid}"
    assert kw["dedupe"] is True
    assert note_fragment in kw["note"]

    row = asyncio.run(_fetch_metric(pg_factory, tid))
    assert row["resolution_status"] == expected_status
    assert row["business_id"] == "aurora"
    assert row["total_tokens"] == FAKE_TOKENS

    # 道歉罐头照常入记忆与交付(交付不因降级缺卡而中断)
    assert stubs.short_adds[0][1] == degraded["output"]
    assert final["output"] == degraded["output"]


@pytest.mark.usefixtures("pg_factory")
def test_waiting_approval_subtask_overrides_resolution_status(monkeypatch, pg_factory):
    tid = "t-seam-waiting"
    stubs = _SettleStubs()
    stubs.patch(monkeypatch)

    _seed_thread(pg_factory, thread_id=tid)
    result = _happy_result()
    result["task_plan"]["subtasks"] = [
        {"id": "s1", "status": "completed", "result": {"waitingForApproval": True}},
    ]

    asyncio.run(_settle(stubs, result, job=_make_job(thread_id=tid)))

    row = asyncio.run(_fetch_metric(pg_factory, tid))
    assert row["resolution_status"] == "waiting_approval"


@pytest.mark.usefixtures("pg_factory")
def test_empty_output_skips_memory_writes_but_still_settles(monkeypatch, pg_factory):
    tid = "t-seam-empty"
    stubs = _SettleStubs()
    stubs.patch(monkeypatch)

    _seed_thread(pg_factory, thread_id=tid)
    result = _happy_result()
    del result["output"]

    final = asyncio.run(_settle(stubs, result, job=_make_job(thread_id=tid)))

    assert stubs.short_adds == [] and stubs.episodic_adds == [] and stubs.long_facts == []
    assert stubs.task_saves, "空输出仍须落任务记忆"
    row = asyncio.run(_fetch_metric(pg_factory, tid))
    assert row["resolution_status"] == "resolved_auto"
    assert stubs.log[-1] == "publish_result", "无输出轮照常发布 result 事件"
    # 反幻觉闸把无输出轮规范化为空串(键存在、值为空),严禁编造文案
    assert final["output"] == ""


class TestMemoryWriteIndependence:
    """三路记忆回写独立降级(2026-10-02 夜审收口):三写曾包在同一个 try 里,
    episodic 抛错会静默连坐跳过 long 事实抽取 —— 单路失败只吞本路。"""

    @pytest.mark.usefixtures("pg_factory")
    def test_episodic_failure_does_not_skip_long_extraction(self, monkeypatch, pg_factory):
        tid = "t-seam-episodic-boom"
        stubs = _SettleStubs()
        stubs.patch(monkeypatch)
        module = importlib.import_module("engine_py.run_agent")

        async def boom(self, summary, score):
            raise RuntimeError("episodic embedding unavailable")

        monkeypatch.setattr(module.EpisodicMemory, "add_event", boom)

        _seed_thread(pg_factory, thread_id=tid)
        final = asyncio.run(_settle(stubs, _happy_result(), job=_make_job(thread_id=tid)))

        assert "episodic_event" not in stubs.log, "故障路不得落事件"
        assert stubs.short_adds and stubs.long_facts, "短期行与长期事实抽取严禁被连坐跳过"
        assert stubs.log[-1] == "publish_result", "交付照常发布"
        assert final["output"] == "您的订单已发出,预计三天内送达。"

    @pytest.mark.usefixtures("pg_factory")
    def test_short_memory_failure_does_not_skip_episodic_and_long(self, monkeypatch, pg_factory):
        tid = "t-seam-short-boom"
        stubs = _SettleStubs()
        stubs.patch(monkeypatch)
        module = importlib.import_module("engine_py.run_agent")

        async def boom(self, role, content, cards=None):
            raise RuntimeError("messages table unavailable")

        monkeypatch.setattr(module.ShortMemory, "add_message", boom)

        _seed_thread(pg_factory, thread_id=tid)
        asyncio.run(_settle(stubs, _happy_result(), job=_make_job(thread_id=tid)))

        assert stubs.short_adds == []
        assert stubs.episodic_adds and stubs.long_facts, "情境与长期两路照常回写"
        assert "task_memory" in stubs.log and stubs.log[-1] == "publish_result"
