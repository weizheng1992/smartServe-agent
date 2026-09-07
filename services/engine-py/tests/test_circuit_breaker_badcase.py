"""熔断信号入坏例池(wayfinder 006)— 熔断打开 → 入池 → 摘要包含 全链路。

以密封 PG 驱动 run_agent 真实主流程:
- 伪图注入 CircuitBreakerOpenError 模拟上游 LLM 熔断拦截(与 003 落地链路
  同构:韧性层 OPEN 拒绝 → 节点兜底豁免上抛 → 图 ainvoke 透传);
- 图级熔断(全局转移 ≥10)走真实结果字典判定路径。
两路均应:session_metrics 落对应 resolution_status + badcase_candidates 入池
(source=circuit_breaker,先验 suspected_defect),run_badcase_digest()(scheduler
6h 周期任务同函数)摘要能消费到新信号源。
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from sqlalchemy import select

from engine_py.db import BadcaseCandidate, SessionMetric
from engine_py.llm import resilience
from engine_py.llm.resilience import CircuitBreakerOpenError, global_circuit_breaker

pytestmark = pytest.mark.usefixtures("pg_factory")


class _OpenBreakerGraph:
    """伪图:ainvoke 即被上游 LLM 熔断拒绝(OPEN)拦截,模拟 003 豁免上抛链路。"""

    async def ainvoke(self, _state):
        raise CircuitBreakerOpenError(global_circuit_breaker.get_status())


class _GraphBreakerGraph:
    """伪图:返回触绘图级熔断的结果(全局转移 12 次 ≥ 10 阈值)。"""

    async def ainvoke(self, _state):
        return {
            "output": "抱歉,当前服务遇到波动。",
            "task_plan": {"subtasks": [], "currentStepIndex": 0},
            "loop_count": 5,
            "global_transitions_count": 12,
            "tool_errors_count": 1,
        }


class _NoopEpisodic:
    def __init__(self, *args, **kwargs):
        pass

    async def add_event(self, *args, **kwargs):
        return None

    async def retrieve_events(self, *args, **kwargs):
        return []


class _NoopLong:
    def __init__(self, *args, **kwargs):
        pass

    async def extract_and_store_fact(self, *args, **kwargs):
        return None

    async def search_relevant_facts(self, *args, **kwargs):
        return []


@pytest.fixture(autouse=True)
def _isolate_llm_and_memory(monkeypatch):
    """熔断器干净出发;替身记忆避开 embedding/LLM;输入 ≤3 字符跳过三路检索。"""
    monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "5")
    global_circuit_breaker.reset()

    # engine_py.__init__ 重导出 run_agent 函数,同名属性遮蔽模块 —— 取 sys.modules 真身
    run_agent_module = importlib.import_module("engine_py.run_agent")

    monkeypatch.setattr(run_agent_module, "EpisodicMemory", _NoopEpisodic)
    monkeypatch.setattr(run_agent_module, "LongMemory", _NoopLong)
    yield
    global_circuit_breaker.reset()


def _run_agent_with_graph(monkeypatch, graph, thread_id: str) -> dict:
    run_agent_module = importlib.import_module("engine_py.run_agent")

    monkeypatch.setattr(run_agent_module, "build_graph", lambda: graph)
    job = run_agent_module.AgentJobInput(
        job_id="",  # 空值:跳过 Redis 事件发布,测试零外联
        thread_id=thread_id,
        user_id="CUST-CB-BADCASE",
        business_id="aurora",
        message="退款",  # ≤3 字符:跳过 embedding 三路检索,零模型加载
    )
    return asyncio.run(run_agent_module.run_agent(job))


async def _fetch_pool_rows(thread_id: str) -> list[BadcaseCandidate]:
    from engine_py.db import get_session

    async with get_session() as session:
        rows = (
            await session.execute(
                select(BadcaseCandidate).where(
                    BadcaseCandidate.conversation_ref == f"thread:{thread_id}"
                )
            )
        ).scalars().all()
        # detach 供断言
        for row in rows:
            _ = row.signal_source, row.suggested_class, row.note
        return list(rows)


async def _fetch_metric_status(thread_id: str) -> str | None:
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                select(SessionMetric.resolution_status).where(SessionMetric.thread_id == thread_id)
            )
        ).scalar_one_or_none()
        return row


def test_llm熔断拦截_信号入池且先验为疑似缺陷(monkeypatch):
    """熔断打开 → 会话降级道歉 + session_metrics 落 llm_circuit_breaker +
    信号入池(source=circuit_breaker / suggested_class=suspected_defect)。"""
    for _ in range(5):  # 连续失败达阈值 → 全局熔断器 OPEN
        global_circuit_breaker.record_failure(now_ms=resilience._now_ms())
    assert global_circuit_breaker.get_status()["state"] == "OPEN"

    thread_id = "dbg_thread_cb_pool_llm"
    result = _run_agent_with_graph(monkeypatch, _OpenBreakerGraph(), thread_id)

    assert "稍后再试" in result["output"]  # 降级道歉回复走通主流程
    assert asyncio.run(_fetch_metric_status(thread_id)) == "llm_circuit_breaker"

    rows = asyncio.run(_fetch_pool_rows(thread_id))
    assert len(rows) == 1
    assert rows[0].signal_source == "circuit_breaker"
    assert rows[0].suggested_class == "suspected_defect"
    assert rows[0].business_id == "aurora"
    assert "LLM 熔断" in rows[0].note


def test_同一会话熔断窗口内重试不重复入池(monkeypatch):
    """dedupe 幂等护栏:OPEN 窗口内同一会话多次回合只入池一条
    (对齐 gatekeeper 转人工挂点"重复呼叫不重复入池"语义)。"""
    for _ in range(5):
        global_circuit_breaker.record_failure(now_ms=resilience._now_ms())

    thread_id = "dbg_thread_cb_pool_dedupe"
    _run_agent_with_graph(monkeypatch, _OpenBreakerGraph(), thread_id)
    _run_agent_with_graph(monkeypatch, _OpenBreakerGraph(), thread_id)  # 用户重试第二回合

    rows = asyncio.run(_fetch_pool_rows(thread_id))
    assert len(rows) == 1


def test_图级熔断_同样入池且备注区分(monkeypatch):
    """图级熔断(转移 ≥10)落 circuit_breaker 终态,入池备注携带转移/错误计数。"""
    thread_id = "dbg_thread_cb_pool_graph"
    _run_agent_with_graph(monkeypatch, _GraphBreakerGraph(), thread_id)

    assert asyncio.run(_fetch_metric_status(thread_id)) == "circuit_breaker"
    rows = asyncio.run(_fetch_pool_rows(thread_id))
    assert len(rows) == 1
    assert rows[0].signal_source == "circuit_breaker"
    assert "图级熔断" in rows[0].note
    assert "12" in rows[0].note


def test_摘要能消费新信号源(monkeypatch):
    """scheduler 6h 周期任务(run_badcase_digest)的池分布摘要包含
    circuit_breaker 新信号源 —— group_by signal_source 自动收纳,无需改摘要。"""
    from engine_py.badcase.digest import run_badcase_digest

    thread_id = "dbg_thread_cb_pool_digest"
    _run_agent_with_graph(monkeypatch, _OpenBreakerGraph(), thread_id)

    summary = asyncio.run(run_badcase_digest())
    distribution = summary["distribution"].get("circuit_breaker", {})
    assert distribution.get("candidate", 0) >= 1


def test_正常会话不入池(monkeypatch):
    """无熔断的普通会话(转移/错误均低于阈值)不产生 circuit_breaker 信号。"""

    class _HealthyGraph:
        async def ainvoke(self, _state):
            return {
                "output": "已为您查询到订单状态。",
                "task_plan": {"subtasks": [], "currentStepIndex": 0},
                "loop_count": 3,
                "global_transitions_count": 4,
                "tool_errors_count": 0,
            }

    thread_id = "dbg_thread_cb_pool_healthy"
    _run_agent_with_graph(monkeypatch, _HealthyGraph(), thread_id)

    assert asyncio.run(_fetch_metric_status(thread_id)) == "resolved_auto"
    assert asyncio.run(_fetch_pool_rows(thread_id)) == []
