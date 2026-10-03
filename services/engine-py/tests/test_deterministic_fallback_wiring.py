"""确定性兜底分发的身份接线钉死(2026-09-30 三处实弹 bug 回归)。

run_agent 双降级臂与 finish 兜底臂都调 deterministic_fallback_answer,
但身份实参曾全部失真:

- run_agent 两臂传 ``job.businessId`` —— AgentJobInput 字段实名
  ``business_id``(camelCase 只是 pydantic alias),属性访问必然
  AttributeError,又被 except 吞掉 → LLM 熔断时确定性兜底从未真正执行过;
- finish 兜底臂读 ``state["userId"]`` / ``state["businessId"]`` ——
  AgentState 从无此两键 → 租户恒落硬编码 "aurora"。

本文件以桩件钉死:两条降级臂必须把真实身份递到分发器;
退货窗时效另钉 naive-UTC 钟口径(_refund_window_lapse_days)。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import importlib

import pytest

from engine_py.llm.resilience import CircuitBreakerOpenError, ContentFilterError

FAKE_FALLBACK_ANSWER = "【兜底】在售活动与您的可用券已如实列出。"


class _FallbackSpy:
    """桩:记录实参并返回哨兵答案,断言兜底臂递进来的身份。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str | None, str, str]] = []

    async def __call__(self, question, thread_id, user_id, business_id="aurora"):
        self.calls.append((question, thread_id, user_id, business_id))
        return FAKE_FALLBACK_ANSWER


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


class _OpenBreakerGraph:
    async def ainvoke(self, _state):
        raise CircuitBreakerOpenError("OPEN(test)")


class _ExplodingGraph:
    async def ainvoke(self, _state):
        raise RuntimeError("图内未捕获异常(测试桩)")


def _make_job():
    run_agent_module = importlib.import_module("engine_py.run_agent")
    return run_agent_module.AgentJobInput(
        job_id="",  # 空值:跳过 Redis 事件发布,测试零外联
        thread_id="t-fallback-wiring",
        user_id="CUST-FB-WIRING",
        business_id="aurora",
        message="退款",  # ≤3 字符:跳过 embedding 三路检索,零模型加载
    )


@pytest.mark.usefixtures("pg_factory")
@pytest.mark.parametrize("graph_cls", [_OpenBreakerGraph, _ExplodingGraph], ids=["breaker", "graph_error"])
def test_run_agent_fallback_receives_job_business_id(monkeypatch, graph_cls):
    run_agent_module = importlib.import_module("engine_py.run_agent")

    monkeypatch.setattr(run_agent_module, "build_graph", lambda: graph_cls())
    monkeypatch.setattr(run_agent_module, "EpisodicMemory", _NoopEpisodic)
    monkeypatch.setattr(run_agent_module, "LongMemory", _NoopLong)
    spy = _FallbackSpy()
    monkeypatch.setattr("engine_py.skills.fallback_dispatcher.deterministic_fallback_answer", spy)

    result = asyncio.run(run_agent_module.run_agent(_make_job()))

    assert result["output"] == FAKE_FALLBACK_ANSWER, "兜底答案应替换道歉罐头"
    assert spy.calls, "降级臂必须真正调到确定性兜底(job.businessId 时代这里从未执行)"
    question, thread_id, user_id, business_id = spy.calls[0]
    assert (question, thread_id, user_id) == ("退款", "t-fallback-wiring", "CUST-FB-WIRING")
    assert business_id == "aurora", "business_id 必须取自 AgentJobInput 实名字段"


@pytest.mark.usefixtures("pg_factory")
def test_finish_fallback_receives_resolved_tenant(monkeypatch):
    finish_module = importlib.import_module("engine_py.graph.nodes.finish")

    class _BoomModel:
        async def ainvoke(self, _prompt):
            raise RuntimeError("LLM 终稿失败(测试桩)")

    monkeypatch.setattr(finish_module, "get_chat_model", lambda: _BoomModel())
    spy = _FallbackSpy()
    monkeypatch.setattr("engine_py.skills.fallback_dispatcher.deterministic_fallback_answer", spy)

    state = {
        "input": "推荐个背包",
        "thread_id": "t-finish-fallback",
        "user_id": "CUST-FINISH-FB",
        "business_config": {"businessId": "nike"},
        # 非空:跳过 ShortMemory 的 DB 自愈读
        "short_memory": [{"role": "user", "content": "推荐个背包"}],
        "intents": [],
        "task_plan": {"subtasks": []},
    }

    result = asyncio.run(finish_module.finish_node(state))

    assert result["output"] == FAKE_FALLBACK_ANSWER
    assert spy.calls, "finish 兜底臂必须真正调到确定性兜底"
    question, thread_id, user_id, business_id = spy.calls[0]
    assert (question, thread_id, user_id) == ("推荐个背包", "t-finish-fallback", "CUST-FINISH-FB")
    assert business_id == "nike", "租户必须来自 _resolve_tenant_id(business_config),严禁硬编码 aurora"


# ── 退货窗时效钟口径(naive-UTC,与库钟 server_default now() 同源)──


def _naive_utc(*args) -> _dt.datetime:
    """naive-UTC 测试钟(到达时间列是 naive DateTime,DTZ 豁免集中此处)。"""
    return _dt.datetime(*args)  # noqa: DTZ001


def _lapse(delivery: str, now: _dt.datetime) -> int:
    from engine_py.tools_registry.order_domain import _refund_window_lapse_days

    return _refund_window_lapse_days(delivery, now=now)


def test_naive_delivery_read_as_db_utc_clock():
    # naive 送达按 DB 钟 UTC 语义直读:2026-09-21T20:00Z → 8d5h → 8 天
    assert _lapse("2026-09-21T20:00:00", _naive_utc(2026, 9, 30, 1, 0)) == 8


def test_aware_delivery_converts_to_utc_not_local_zone():
    # +08:00 串折 UTC(=2026-09-29T18:00Z)→ 7h → 0 天;不随宿主机时区漂移
    assert _lapse("2026-09-30T02:00:00+08:00", _naive_utc(2026, 9, 30, 1, 0)) == 0


def test_window_boundary_not_inflated_by_local_clock():
    # 真时效 6d17h → 6 天;旧实现在 UTC+8 宿主机读成 7d1h=7 天,窗口 6 时误拦
    assert _lapse("2026-09-23T08:00:00", _naive_utc(2026, 9, 30, 1, 0)) == 6


def test_unparseable_delivery_fails_open_zero_days():
    assert _lapse("不是日期", _naive_utc(2026, 9, 30)) == 0


# ── 终端兜底诚实化(2026-10-03 内容过滤实弹)────────────────────────────────
# 旧终端罐头谎称「已由客服系统处理」并拼工具 JSON 详情(output_guard 还得
# 专门剥离),实际什么都没发生 —— 过度承诺即投诉源。内容过滤(400 code
# 1301)确定性拒绝时同理:词面可路由部分真答,答不了才诚实拒答。


class _NoneFallback:
    """桩:分发器无能力命中,返回 None。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, question, thread_id, user_id, business_id="aurora"):
        self.calls.append(question)


class _FilteredModel:
    async def ainvoke(self, _prompt):
        raise ContentFilterError("供应商内容过滤拦截输入(code 1301): 故意触发")


_FINISH_STATE = {
    "input": "你们支持比特币支付吗？",
    "thread_id": "t-finish-honest",
    "user_id": "CUST-FINISH-HONEST",
    "business_config": {"businessId": "nike"},
    "short_memory": [{"role": "user", "content": "你们支持比特币支付吗？"}],
    "intents": [],
    "task_plan": {"subtasks": []},
}


def _run_finish(monkeypatch, model) -> dict:
    finish_module = importlib.import_module("engine_py.graph.nodes.finish")
    monkeypatch.setattr(finish_module, "get_chat_model", lambda: model)
    return asyncio.run(finish_module.finish_node(dict(_FINISH_STATE)))


def test_content_filter_routes_deterministic_answer_first(monkeypatch):
    """过滤输入词面可路由(如夹带显式单号)的部分仍由确定性兜底真答。"""
    spy = _FallbackSpy()
    monkeypatch.setattr("engine_py.skills.fallback_dispatcher.deterministic_fallback_answer", spy)

    result = _run_finish(monkeypatch, _FilteredModel())

    assert result["output"] == FAKE_FALLBACK_ANSWER, "词面可路由部分必须真答,不得直接拒答"
    assert spy.calls, "内容过滤臂必须真正调到确定性兜底"
    question, thread_id, user_id, business_id = spy.calls[0]
    assert (question, thread_id, user_id) == ("你们支持比特币支付吗？", "t-finish-honest", "CUST-FINISH-HONEST")
    assert business_id == "nike", "内容过滤臂身份接线与 generic 臂同口径"


def test_content_filter_dead_end_honest_refusal(monkeypatch):
    none_fb = _NoneFallback()
    monkeypatch.setattr("engine_py.skills.fallback_dispatcher.deterministic_fallback_answer", none_fb)

    result = _run_finish(monkeypatch, _FilteredModel())

    out = result["output"]
    assert none_fb.calls, "内容过滤臂必须先过确定性兜底再拒答"
    assert "暂不支持在线解答" in out, f"必须诚实拒答: {out}"
    assert "客服系统处理" not in out, "严禁谎称已处理"
    assert "执行详情" not in out, "工具 JSON 详情不得拼进话术"


def test_generic_failure_dead_end_honest_degradation(monkeypatch):
    """generic 终端(旧谎报罐头位置):如实告知未完成 + 指引重试/转人工。"""

    class _BoomModel:
        async def ainvoke(self, _prompt):
            raise RuntimeError("LLM 终稿失败(测试桩)")

    none_fb = _NoneFallback()
    monkeypatch.setattr("engine_py.skills.fallback_dispatcher.deterministic_fallback_answer", none_fb)

    result = _run_finish(monkeypatch, _BoomModel())

    out = result["output"]
    assert "暂时未能完成处理" in out, f"必须如实告知未完成: {out}"
    assert "转人工" in out, "须指引真实存在的规则层转人工意图"
    assert "客服系统处理" not in out and "执行详情" not in out
