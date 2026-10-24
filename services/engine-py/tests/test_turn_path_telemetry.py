"""AI 用量面板写侧契约册(docs/ai-usage-panel.md P0-1)。

钉面:①turn_path 路由映射闭集(triage 全部 route_key 家族);②旁路收口返回
state 携带 turn_path(轮路径一等公民);③triage 节点对非旁路出口默认 deep_path;
④llm_call_logs 行携带 job_id(轮↔调用精确关联,CallContext 现成字段入行);
⑤进图前问候旁路补写零 token session_metrics 行(此前该路径完全不落库,
轮数统计缺行)。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from engine_py.db import SessionMetric, get_session
from engine_py.llm import telemetry as llm_telemetry
from engine_py.triage import IntentTriageEngine
from engine_py.triage.intent_triage_engine import turn_path_for_route


@pytest.mark.parametrize(
    ("route_key", "expected"),
    [
        # 问候族(含进图前旁路的同语义)
        ("rule_greeting", "greeting"),
        # 缓存/重复拦截(零 LLM 复放)
        ("super_semantic_cache", "semantic_cache"),
        ("duplicate_bypass", "duplicate_bypass"),
        # 咨询直答快轨族(≈1 次调用;缓存复放与直答在库内不可区分,口径如实合并)。
        # consult_no_rag 刻意不在映射内:RAG 空弱回落轮走主链 finish 终稿,
        # 不经旁路出口(见 _BYPASS_TURN_PATH_EXACT 注),落 deep_path 才诚实。
        ("rag_consult_direct", "rag_direct"),
        ("rag_consult_direct_llm", "rag_direct"),
        # 澄清反问族(0.5 置信级联 + 槽位澄清)
        ("confidence_clarify", "clarify"),
        ("slot_clarification_structured", "clarify"),
        ("slot_clarification_fastpath", "clarify"),
        # 其余确定性旁路(罐头拒绝/范围外/图片消歧)
        ("rule_empty", "bypass_other"),
        ("rule_symbols", "bypass_other"),
        ("rule_length_limit", "bypass_other"),
        ("rule_exit_conversation", "bypass_other"),
        ("llm_out_of_scope", "bypass_other"),
        ("image_product_no_orders", "bypass_other"),
        ("image_product_no_match", "bypass_other"),
        ("image_product_select", "bypass_other"),
        # 未来新增路由键默认归其余旁路,不静默落 deep_path
        ("some_future_route", "bypass_other"),
    ],
)
def test_turn_path_mapping_closure(route_key: str, expected: str):
    assert turn_path_for_route(route_key) == expected


def test_bypass_result_carries_turn_path():
    """handle_immediate_bypass 返回 state 即带路径(所有旁路出口的单点)。"""

    async def run():
        result = await IntentTriageEngine.handle_immediate_bypass(
            {"input": "你好"}, "super_semantic_cache", "命中缓存", [], "semantic_cache", 1.0
        )
        assert result["turn_path"] == "semantic_cache"

    asyncio.run(run())


def test_triage_node_defaults_deep_path(monkeypatch: pytest.MonkeyPatch):
    """非旁路出口(走 planner/finish 主链)由 triage 节点单点默认 deep_path。"""
    from engine_py.graph.nodes import triage as triage_node_module

    async def fake_process(state: dict) -> dict:
        return {"intents": [{"intent": "order_status", "confidence": 0.9}]}

    monkeypatch.setattr(IntentTriageEngine, "process", staticmethod(fake_process))
    result = asyncio.run(triage_node_module.triage_node({"input": "查订单"}))
    assert result["turn_path"] == "deep_path"


def test_triage_node_preserves_bypass_turn_path(monkeypatch: pytest.MonkeyPatch):
    from engine_py.graph.nodes import triage as triage_node_module

    async def fake_process(state: dict) -> dict:
        return {"intents": [], "turn_path": "semantic_cache"}

    monkeypatch.setattr(IntentTriageEngine, "process", staticmethod(fake_process))
    result = asyncio.run(triage_node_module.triage_node({"input": "运费多少"}))
    assert result["turn_path"] == "semantic_cache"


def test_telemetry_row_carries_job_id(monkeypatch: pytest.MonkeyPatch):
    """llm_call_logs 行携带 job_id —— 轮下钻调用明细的关联键。"""
    captured: dict = {}
    captured_event = asyncio.Event()

    async def fake_persist(row: dict) -> None:
        captured.update(row)
        captured_event.set()

    monkeypatch.setattr(llm_telemetry, "_persist", fake_persist)

    async def run():
        llm_telemetry.bind_llm_call_context(thread_id="t1", business_id="b1", job_id="j1")
        handler = llm_telemetry.LlmCallTelemetryHandler()
        run_id = uuid.uuid4()
        handler.on_llm_start({}, [], run_id=run_id)
        generation = SimpleNamespace(
            message=SimpleNamespace(
                usage_metadata={"input_tokens": 12, "output_tokens": 8},
                response_metadata={"model_name": "glm-test"},
            ),
            generation_info=None,
        )
        await handler.on_llm_end(SimpleNamespace(generations=[[generation]]), run_id=run_id)
        await asyncio.wait_for(captured_event.wait(), timeout=2)
        llm_telemetry.take_thread_token_total("t1")  # 清理进程内计数器

    asyncio.run(run())
    assert captured["job_id"] == "j1"
    assert captured["thread_id"] == "t1"
    assert captured["business_id"] == "b1"
    assert captured["tokens_in"] == 12
    assert captured["tokens_out"] == 8


@pytest.mark.usefixtures("pg_factory")
def test_greeting_bypass_writes_zero_token_row():
    """进图前问候旁路补写零 token 行:turn_path='greeting',轮数统计不再缺行。"""
    import importlib

    run_agent_module = importlib.import_module("engine_py.run_agent")

    tid = f"tpr_{uuid.uuid4().hex[:12]}"
    uid = f"u_{uuid.uuid4().hex[:8]}"
    biz = f"tpr_{uuid.uuid4().hex[:8]}"

    async def run():
        async with get_session() as session:
            await session.execute(
                text(
                    'INSERT INTO threads (id, "user_id", business_id, status) '
                    "VALUES (:t, :u, :b, 'active') ON CONFLICT (id) DO NOTHING"
                ).bindparams(t=tid, u=uid, b=biz)
            )
            await session.commit()

        await run_agent_module._record_greeting_bypass_metric(biz, tid, "job_g1", 12.5)

        async with get_session() as session:
            row = (
                await session.execute(select(SessionMetric).where(SessionMetric.thread_id == tid))
            ).scalars().one()
        assert row.turn_path == "greeting"
        assert row.total_tokens == 0
        assert row.calculated_cost_usd == 0
        assert row.job_id == "job_g1"
        assert row.resolution_status == "resolved_auto"

    asyncio.run(run())
