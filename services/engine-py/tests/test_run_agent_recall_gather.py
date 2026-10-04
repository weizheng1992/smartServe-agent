"""三路召回 gather 独立降级契约(run_agent 预装配段,2026-10-02 夜审补钉)。

long_facts / episodic_events / rag_documents 三路经
``asyncio.gather(..., return_exceptions=True)`` 并发召回:单路抛错必须
只把本路降级为空列表,其余两路原样注入图初始状态 —— 降级不得扩散,
也不得让异常冒泡炸回合。此前该不变量只有实现、没有断言。
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from engine_py.llm.resilience import CircuitBreakerOpenError

FAKE_FALLBACK_ANSWER = "【兜底】召回降级轮照常诚实作答。"


class _CapturingBreakerGraph:
    """捕获递入的初始状态后走熔断臂:测试不触真图、不经 LLM。"""

    captured: list[dict] = []

    async def ainvoke(self, state):
        type(self).captured.append(state)
        raise CircuitBreakerOpenError("OPEN(test)")


class _BoomLongMemory:
    def __init__(self, *args, **kwargs):
        pass

    async def search_relevant_facts(self, *args, **kwargs):
        raise RuntimeError("long memory store unavailable")

    async def extract_and_store_fact(self, *args, **kwargs):
        return None


class _HealthyEpisodic:
    def __init__(self, *args, **kwargs):
        pass

    async def retrieve_events(self, *args, **kwargs):
        return [{"summary": "上次退货事件", "importance": 7}]

    async def add_event(self, *args, **kwargs):
        return None


class _HealthyRAG:
    def __init__(self, *args, **kwargs):
        pass

    async def search_relevant_docs(self, *args, **kwargs):
        return [{"source": "refund_policy.md", "text": "七天无理由"}]


class _FakeEmbedder:
    async def aembed_query(self, _text):
        return [0.1, 0.2, 0.3]


class _FallbackSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def __call__(self, question, thread_id, user_id, business_id="aurora"):
        self.calls.append((question, thread_id, user_id, business_id))
        return FAKE_FALLBACK_ANSWER


@pytest.mark.usefixtures("pg_factory")
def test_one_failed_recall_arm_degrades_to_empty_others_inject(monkeypatch):
    run_agent_module = importlib.import_module("engine_py.run_agent")
    _CapturingBreakerGraph.captured = []

    monkeypatch.setattr(run_agent_module, "build_graph", lambda: _CapturingBreakerGraph())
    monkeypatch.setattr(run_agent_module, "LongMemory", _BoomLongMemory)
    monkeypatch.setattr(run_agent_module, "EpisodicMemory", _HealthyEpisodic)
    monkeypatch.setattr(run_agent_module, "ContextualRAG", _HealthyRAG)
    monkeypatch.setattr(run_agent_module, "get_embedding_model", lambda: _FakeEmbedder())
    spy = _FallbackSpy()
    monkeypatch.setattr("engine_py.skills.fallback_dispatcher.deterministic_fallback_answer", spy)

    job = run_agent_module.AgentJobInput(
        job_id="",  # 空 job_id:跳过 Redis 事件发布
        thread_id="t-recall-gather",
        user_id="CUST-RECALL",
        business_id="aurora",
        message="退货政策是什么样的",  # >3 字符:触发三路召回 gather
    )
    result = asyncio.run(run_agent_module.run_agent(job))

    assert result["output"] == FAKE_FALLBACK_ANSWER, "召回故障轮照常降级交付"
    assert _CapturingBreakerGraph.captured, "熔断臂前必须已构建图初始状态"
    state = _CapturingBreakerGraph.captured[0]
    assert state["long_memory_facts"] == [], "故障路降级为空列表,严禁异常冒泡"
    assert state["episodic_events"], "其余两路严禁被连坐清空(情境记忆)"
    assert state["rag_documents"], "其余两路严禁被连坐清空(RAG 切片)"
    assert spy.calls, "降级臂必须真正调到确定性兜底"


class _TurnIntentGraph:
    """捕获初始状态后按预定 intents 返回终态:驱动 settle 写回缝,不触真图/LLM。"""

    captured: list[dict] = []

    def __init__(self, intents):
        self._intents = intents

    async def ainvoke(self, state):
        type(self).captured.append(state)
        return {
            **state,
            "output": "好的,已为您处理。",
            "task_plan": {"goal": "g", "subtasks": [], "currentStepIndex": 0},
            "intents": self._intents,
        }


class _RecordingEpi:
    added: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    async def retrieve_events(self, *args, **kwargs):
        return []

    async def add_event(self, text, importance, **kwargs):
        type(self).added.append(text)


class _QuietLong:
    def __init__(self, *args, **kwargs):
        pass

    async def search_relevant_facts(self, *args, **kwargs):
        return []

    async def extract_and_store_fact(self, *args, **kwargs):
        return None


class _QuietRag:
    def __init__(self, *args, **kwargs):
        pass

    async def search_relevant_docs(self, *args, **kwargs):
        return []


@pytest.mark.usefixtures("pg_factory")
def test_episodic_writeback_only_for_action_turns(monkeypatch):
    """P3(2026-10-03):情境记忆只记业务动作回合 —— 咨询/问答侧回合不再每回合
    写「Handled conversation thread...」样板并白付一次 embedding(稀释
    [MEMORY OF PAST EVENTS] 召回面 + 徒增每回合成本);动作形回合(consult
    侧补集,与坏例冲突检测同口径)照旧入池。"""
    run_agent_module = importlib.import_module("engine_py.run_agent")
    _RecordingEpi.added = []

    monkeypatch.setattr(run_agent_module, "EpisodicMemory", _RecordingEpi)
    monkeypatch.setattr(run_agent_module, "LongMemory", _QuietLong)
    monkeypatch.setattr(run_agent_module, "ContextualRAG", _QuietRag)
    monkeypatch.setattr(run_agent_module, "get_embedding_model", lambda: _FakeEmbedder())

    def _run(intents, message):
        _TurnIntentGraph.captured = []
        monkeypatch.setattr(run_agent_module, "build_graph", lambda: _TurnIntentGraph(intents))
        job = run_agent_module.AgentJobInput(
            job_id="",  # 空 job_id:跳过 Redis 事件发布
            thread_id="t-episodic-gate",
            user_id="CUST-EPI",
            business_id="aurora",
            message=message,
        )
        return asyncio.run(run_agent_module.run_agent(job))

    # 咨询/问答侧回合(general_query ∈ CONSULT_SIDE_INTENTS):不写 episodic
    out = _run([{"intent": "general_query", "confidence": 0.9}], "退货政策是什么样的")
    assert out["output"]
    assert _RecordingEpi.added == [], "纯问答回合不得再写情境记忆样板"

    # 动作形回合(refund ∉ consult 侧):照旧入池
    out = _run([{"intent": "refund", "confidence": 0.95}], "帮我退了 AURORA-ORD-2026-9081")
    assert out["output"]
    assert len(_RecordingEpi.added) == 1, f"动作回合应写情境记忆,实得 {len(_RecordingEpi.added)}"
    assert "Output summary" in _RecordingEpi.added[0]
