"""LLM 韧性层单测 — 熔断状态机 / 指数退避 / 超时中断(wayfinder 003)。

合成时钟直打 CircuitBreaker 状态转移;resilient_ainvoke 以伪调用工厂驱动
退避/超时/熔断联动;状态事件发布经 monkeypatch 截获(不触 Redis)。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from engine_py.llm import resilience
from engine_py.llm.resilience import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    global_circuit_breaker,
    resilient_ainvoke,
    resilient_invoke,
)
from engine_py.llm.telemetry import bind_llm_call_context


@pytest.fixture(autouse=True)
def _fast_retry_env(monkeypatch):
    """退避与超时参数压缩到毫秒级,测试秒回;每测从干净熔断器出发。"""
    monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_RETRY_INITIAL_DELAY_MS", "1")
    global_circuit_breaker.reset()
    yield
    global_circuit_breaker.reset()


class TestCircuitBreaker:
    def test_stays_closed_below_threshold(self, monkeypatch):
        monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "5")
        cb = CircuitBreaker()
        for _ in range(4):
            cb.record_failure(now_ms=0)
        assert cb.is_open(now_ms=1) is False
        assert cb.get_status(now_ms=1)["state"] == "CLOSED"

    def test_opens_at_threshold_and_rejects_during_cooldown(self, monkeypatch):
        monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "5")
        cb = CircuitBreaker()
        for _ in range(5):
            cb.record_failure(now_ms=0)
        assert cb.is_open(now_ms=1_000) is True
        status = cb.get_status(now_ms=1_000)
        assert status["state"] == "OPEN"
        assert status["failureCount"] == 5
        assert status["nextAttemptInMs"] == 29_000  # 30s 冷却剩 29s

    def test_half_open_after_cooldown_then_success_closes(self, monkeypatch):
        monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "5")
        monkeypatch.setenv("LLM_CIRCUIT_COOLDOWN_SECONDS", "30")
        cb = CircuitBreaker()
        for _ in range(5):
            cb.record_failure(now_ms=0)
        assert cb.is_open(now_ms=30_000) is False  # 冷却期满 → HALF_OPEN 放行探测
        assert cb.get_status(now_ms=30_000)["state"] == "HALF_OPEN"

        cb.record_success()  # 探测成功 → 归零回 CLOSED
        closed = cb.get_status(now_ms=30_100)
        assert closed["state"] == "CLOSED"
        assert closed["failureCount"] == 0

    def test_half_open_probe_failure_reopens_with_new_cooldown(self, monkeypatch):
        monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "5")
        monkeypatch.setenv("LLM_CIRCUIT_COOLDOWN_SECONDS", "30")
        cb = CircuitBreaker()
        for _ in range(5):
            cb.record_failure(now_ms=0)
        assert cb.is_open(now_ms=30_000) is False  # HALF_OPEN

        cb.record_failure(now_ms=30_500)  # 探测失败 → 立即重回 OPEN,冷却自此刻重置
        assert cb.get_status(now_ms=30_500)["state"] == "OPEN"
        assert cb.is_open(now_ms=31_000) is True
        assert cb.is_open(now_ms=60_500) is False  # 新冷却期满

    def test_success_resets_consecutive_count(self, monkeypatch):
        monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "5")
        cb = CircuitBreaker()
        for _ in range(4):
            cb.record_failure(now_ms=0)
        cb.record_success()
        for _ in range(4):
            cb.record_failure(now_ms=1)
        # 若计数未归零,4+4=8 早已 OPEN;归零重计 → 仍 CLOSED
        assert cb.get_status(now_ms=2)["state"] == "CLOSED"

    def test_success_resets_breaker_consecutive_count(self, monkeypatch):
        """回归钉:成功路径必须 record_success(TS recordSuccess)——否则计数只增
        不减,分散在任意时间窗的失败累积后误开熔断且永不自愈。"""
        monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "5")
        for _ in range(4):
            global_circuit_breaker.record_failure(now_ms=0)

        def healthy():
            async def _call():
                return "ok"

            return _call()

        assert asyncio.run(resilient_ainvoke(healthy)) == "ok"
        assert global_circuit_breaker.get_status(now_ms=1)["failureCount"] == 0
        assert global_circuit_breaker.get_status(now_ms=1)["state"] == "CLOSED"

    def test_threshold_env_override(self, monkeypatch):
        monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "2")
        cb = CircuitBreaker()
        cb.record_failure(now_ms=0)
        cb.record_failure(now_ms=0)
        assert cb.get_status(now_ms=1)["state"] == "OPEN"


class TestResilientAinvoke:
    @staticmethod
    def _capture_sleep(monkeypatch) -> list[float]:
        delays: list[float] = []

        async def fake_sleep(delay: float) -> None:
            delays.append(delay)

        monkeypatch.setattr(resilience, "_sleep", fake_sleep)
        return delays

    def test_retries_with_exponential_backoff_then_succeeds(self, monkeypatch):
        delays = self._capture_sleep(monkeypatch)
        calls = {"n": 0}

        def flaky():
            async def _call():
                calls["n"] += 1
                if calls["n"] < 3:
                    raise RuntimeError("network glitch")
                return "ok"

            return _call()

        assert asyncio.run(resilient_ainvoke(flaky)) == "ok"
        assert calls["n"] == 3
        assert delays == [0.001, 0.002]  # 初始 1ms 逐次翻倍

    def test_exhausted_retries_record_single_failure_and_reraise(self, monkeypatch):
        self._capture_sleep(monkeypatch)
        monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "5")
        calls = {"n": 0}

        def always_fails():
            async def _call():
                calls["n"] += 1
                raise RuntimeError("provider down")

            return _call()

        with pytest.raises(RuntimeError, match="provider down"):
            asyncio.run(resilient_ainvoke(always_fails))
        assert calls["n"] == 3  # 3 次尝试后透传原始异常
        # 穷尽重试的最终失败才计入熔断(计 1 次,非 3 次)
        assert global_circuit_breaker.get_status()["failureCount"] == 1
        assert global_circuit_breaker.get_status()["state"] == "CLOSED"

    def test_repeated_exhaustion_eventually_opens_breaker(self, monkeypatch):
        self._capture_sleep(monkeypatch)
        monkeypatch.setenv("LLM_CIRCUIT_MAX_FAILURES", "2")

        def always_fails():
            async def _call():
                raise RuntimeError("provider down")

            return _call()

        for _ in range(2):  # 两轮穷尽 → 计 2 次熔断计数 → OPEN
            with pytest.raises(RuntimeError):
                asyncio.run(resilient_ainvoke(always_fails))
        assert global_circuit_breaker.get_status()["state"] == "OPEN"

    def test_rejects_immediately_when_open_without_calling_model(self):
        global_circuit_breaker.record_failure(now_ms=resilience._now_ms())
        global_circuit_breaker.record_failure(now_ms=resilience._now_ms())
        global_circuit_breaker.record_failure(now_ms=resilience._now_ms())
        global_circuit_breaker.record_failure(now_ms=resilience._now_ms())
        global_circuit_breaker.record_failure(now_ms=resilience._now_ms())
        assert global_circuit_breaker.get_status()["state"] == "OPEN"

        called = {"n": 0}

        def model():
            async def _call():
                called["n"] += 1
                return "never"

            return _call()

        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            asyncio.run(resilient_ainvoke(model))
        assert called["n"] == 0  # 熔断开启:模型调用零触发
        assert "熔断" in str(exc_info.value)
        assert exc_info.value.status["state"] == "OPEN"

    def test_timeout_interrupts_attempt_and_counts_as_failure(self, monkeypatch):
        self._capture_sleep(monkeypatch)
        monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0.01")
        calls = {"n": 0}

        def slow():
            async def _call():
                calls["n"] += 1
                await asyncio.sleep(0.5)  # 远超 10ms 超时,每次尝试必被中断
                return "late"

            return _call()

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(resilient_ainvoke(slow))
        assert calls["n"] == 3  # 超时视同失败:参与退避重试后透传

    def test_timeout_disabled_when_env_nonpositive(self, monkeypatch):
        monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0")

        def slowish():
            async def _call():
                await asyncio.sleep(0.05)
                return "ok"

            return _call()

        assert asyncio.run(resilient_ainvoke(slowish)) == "ok"


class TestResilientInvoke:
    def test_sync_path_retries_and_reraises(self, monkeypatch):
        monkeypatch.setenv("LLM_RETRY_MAX_ATTEMPTS", "2")
        monkeypatch.setattr(resilience.time, "sleep", lambda _: None)
        calls = {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise RuntimeError("sync down")

        with pytest.raises(RuntimeError):
            resilient_invoke(always_fails)
        assert calls["n"] == 2


class TestJobStatusEmission:
    @staticmethod
    def _capture_publish(monkeypatch) -> list[tuple]:
        events: list[tuple] = []

        async def fake_publish(job_id, kind, payload):
            events.append((job_id, kind, payload))

        monkeypatch.setattr(resilience, "publish_agent_event", fake_publish)
        return events

    def test_retry_emits_executing_status_to_bound_job(self, monkeypatch):
        events = self._capture_publish(monkeypatch)
        monkeypatch.setattr(resilience, "_sleep", self._noop_sleep())
        bind_llm_call_context(thread_id="t1", business_id="b1", job_id="job_retry")
        calls = {"n": 0}

        def flaky():
            async def _call():
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("glitch")
                return "ok"

            return _call()

        asyncio.run(resilient_ainvoke(flaky))
        executing = [e for e in events if e[2].get("status") == "executing"]
        assert len(executing) == 1
        assert executing[0][0] == "job_retry"
        assert "第 2 次" in executing[0][2]["message"]

    def test_open_breaker_emits_circuit_status_before_raise(self, monkeypatch):
        events = self._capture_publish(monkeypatch)
        bind_llm_call_context(thread_id="t2", business_id="b2", job_id="job_open")
        for _ in range(5):
            global_circuit_breaker.record_failure(now_ms=resilience._now_ms())
        assert global_circuit_breaker.get_status()["state"] == "OPEN"

        def model():
            async def _call():
                return "never"

            return _call()

        with pytest.raises(CircuitBreakerOpenError):
            asyncio.run(resilient_ainvoke(model))
        breaker_events = [e for e in events if e[2].get("status") == "circuit_breaker_open"]
        assert len(breaker_events) == 1
        assert breaker_events[0][0] == "job_open"
        assert "熔断" in breaker_events[0][2]["message"]

    def test_no_job_context_skips_emission_silently(self, monkeypatch):
        events = self._capture_publish(monkeypatch)
        monkeypatch.setattr(resilience, "_sleep", self._noop_sleep())
        bind_llm_call_context(thread_id="t3", business_id="b3", job_id=None)

        def flaky():
            async def _call():
                raise RuntimeError("glitch")

            return _call()

        with pytest.raises(RuntimeError):
            asyncio.run(resilient_ainvoke(flaky))
        assert events == []  # 无 job 归因:不发布,也不得因发布失败阻断

    @staticmethod
    def _noop_sleep():
        async def noop(_delay: float) -> None:
            return None

        return noop


class TestChatModelWiring:
    """接线回归钉:模型子类的重试工厂 lambda 必须正确解析 super() 代理
    (零参 super 不进 lambda 帧,2026-09-07 曾因此 RuntimeError: no arguments)。"""

    def test_ainvoke_routes_through_resilient_wrapper(self, monkeypatch):
        from langchain_openai import ChatOpenAI

        from engine_py.llm.chat import get_chat_model

        async def fake_super_ainvoke(self, input, config=None, **kwargs):
            return f"mocked:{input}"

        monkeypatch.setattr(ChatOpenAI, "ainvoke", fake_super_ainvoke)
        model = get_chat_model()
        assert asyncio.run(model.ainvoke("hello")) == "mocked:hello"

    def test_invoke_routes_through_resilient_wrapper(self, monkeypatch):
        from langchain_openai import ChatOpenAI

        from engine_py.llm.chat import get_chat_model

        def fake_super_invoke(self, input, config=None, **kwargs):
            return f"mocked:{input}"

        monkeypatch.setattr(ChatOpenAI, "invoke", fake_super_invoke)
        model = get_chat_model()
        assert model.invoke("hello") == "mocked:hello"


class TestNodeFallbackCarveOut:
    """节点兜底豁免:宽 except 前置 CircuitBreakerOpenError 上抛 —— 上游熔断
    非节点级可恢复,若被兜底吞掉,run_agent 的 job 级降级与 llm_circuit_breaker
    落盘永不触达(2026-09-07 Spec 评审发现)。以 validator 为代表钉死该模式。"""

    def test_validator_node_reraises_instead_of_default_yes(self, monkeypatch):
        from engine_py.graph.nodes import validator as validator_module
        from engine_py.llm import CircuitBreakerOpenError as OpenErr

        class _BrokenModel:
            async def ainvoke(self, _prompt):
                raise OpenErr({"state": "OPEN", "failureCount": 5, "nextAttemptInMs": 30_000})

        monkeypatch.setattr(validator_module, "get_chat_model", lambda: _BrokenModel())
        state = {
            "task_plan": {
                "subtasks": [{"description": "step", "result": {"output": "x", "error": "boom"}}],
                "currentStepIndex": 0,
            },
        }
        with pytest.raises(OpenErr):
            asyncio.run(validator_module.validator_node(state))


class TestDegradedBreakerResult:
    def test_degraded_result_shape_is_graph_consumable(self):
        from engine_py.run_agent import _degraded_apology_result

        result = _degraded_apology_result()
        assert "稍后再试" in result["output"]
        assert result["task_plan"]["subtasks"] == []
        assert result["loop_count"] == 0
        assert result["global_transitions_count"] == 0
        assert result["tool_errors_count"] == 0


def test_total_deadline_caps_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """总预算闸(2026-09-25 挂死修复):每尝试各有超时时,三次慢尝试 ≈ 6 分钟
    才降级 —— 用户端无限 loading。总预算耗尽须立即放弃,不再进入下一尝试。"""
    import asyncio as _aio

    from engine_py.llm import resilience as R

    async def slow_attempt():
        await _aio.sleep(30)  # 远超预算
        return "ok"

    monkeypatch.setattr(R, "_max_attempts", lambda: 5)
    monkeypatch.setattr(R, "_initial_delay_ms", lambda: 1)
    monkeypatch.setattr(R, "_timeout_seconds", lambda: 30.0)
    monkeypatch.setenv("LLM_TOTAL_DEADLINE_SECONDS", "3")

    started = time.time()
    with pytest.raises(TimeoutError, match="总预算"):
        asyncio.run(R.resilient_ainvoke(slow_attempt))
    elapsed = time.time() - started
    assert elapsed < 10, f"总预算必须在 ~3s 生效,实耗 {elapsed:.1f}s(未超10s)"
