"""仲裁留痕与终局决策单点落库(intent-arbitration 01,2026-09-10)。

钉死三件事:
1. ``log_intent_to_db`` 写全 candidates / winner / arbitration_reason 三列
   (密封 PG,Alembic 0007 真实 schema);
2. 槽位层高置信放行 × skill fast-track 命中 → 同一输入只落**一行**
   (method=skill_fast_track,修复旧行为 slot_extractor+skill_fast_track
   双写两行且无仲裁记录);未命中技能才落 slot_extractor 行 —— 两态均带
   candidates 提议快照与裁决理由;
3. node 归因兜底:节点内直调无 langgraph_node 元数据时,llm_call_logs 行
   的 node 取自 ``bind_llm_call_node`` 的 ContextVar;元数据存在时优先。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from engine_py.db import IntentLog, Thread, get_session
from engine_py.llm import telemetry
from engine_py.llm.telemetry import (
    LlmCallTelemetryHandler,
    bind_llm_call_context,
    bind_llm_call_node,
)
from engine_py.skills import SkillRegistry
from engine_py.triage import intent_triage_engine as triage_mod
from engine_py.triage.intent_triage_engine import IntentTriageEngine


# ---- 共享假件(与 test_consult_fast_path 同构) ----


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class _FakeTaskMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_task_state(self) -> dict | None:
        return None

    async def save_task_state(self, state: dict) -> None:
        return None


class _FakeSkill:
    def __init__(self, skill_id: str, result: dict) -> None:
        self.metadata = {"id": skill_id}
        self._result = result
        self.executed_with: dict | None = None

    async def execute(self, context: dict) -> dict:
        self.executed_with = context
        return self._result


def _order_query_state() -> dict:
    """order_query@0.92 齐备槽位(实测 SlotExtractor),触发高置信放行路径。"""
    return {
        "thread_id": "thread_arbit_test",
        "user_id": "u_arbit",
        "input": "查一下订单 ORD-10001 的物流状态",
        "image_urls": [],
        "input_embedding": [],
        "business_config": {"businessId": "ecommerce"},
    }


def _record_logs(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """把终局落库调用记到列表(签名 kwargs 一并留存)。"""
    calls: list[dict] = []

    async def _recording_log(thread_id, input_text, intents, method, confidence, **kwargs):
        calls.append(
            {
                "thread_id": thread_id,
                "input_text": input_text,
                "intents": intents,
                "method": method,
                "confidence": confidence,
                **kwargs,
            }
        )

    monkeypatch.setattr(IntentTriageEngine, "log_intent_to_db", _recording_log)
    return calls


def _wire_common(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
    monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)


class TestSinglePointTerminalWrite:
    """终局决策单点落库:fast-track 命中/未命中两态各只写一行,且带仲裁留痕。"""

    def test_fast_track_hit_writes_single_row_with_candidates(self, monkeypatch):
        _wire_common(monkeypatch)
        calls = _record_logs(monkeypatch)
        fake_skill = _FakeSkill(
            "skill_order_query",
            {"success": True, "nextAction": "finish", "output": "订单 ORD-10001 已发货。"},
        )
        monkeypatch.setattr(SkillRegistry, "find_matching_skill", classmethod(lambda cls, ctx: fake_skill))

        result = asyncio.run(IntentTriageEngine.process(_order_query_state()))

        # 旧行为在此落两行:slot_extractor 预写 + skill_fast_track bypass 写
        assert len(calls) == 1, f"同一输入必须单点落库,实得 {len(calls)} 行"
        row = calls[0]
        assert row["method"] == "skill_fast_track"
        assert row["intents"][0]["intent"] == "order_query"
        assert row["arbitration_reason"] == "skill_fast_track_skill_order_query"
        layers = [c["layer"] for c in row["candidates"]]
        assert layers == ["slot_extractor", "skill_fast_track"], "候选须呈现槽位+技能两提议"
        assert row["candidates"][0]["intent"] == "order_query"
        assert "订单 ORD-10001 已发货" in result["output"]

    def test_fast_track_miss_logs_slot_extractor_row(self, monkeypatch):
        _wire_common(monkeypatch)
        calls = _record_logs(monkeypatch)
        monkeypatch.setattr(SkillRegistry, "find_matching_skill", classmethod(lambda cls, ctx: None))

        result = asyncio.run(IntentTriageEngine.process(_order_query_state()))

        assert len(calls) == 1, f"未命中技能应只落 slot_extractor 一行,实得 {len(calls)} 行"
        row = calls[0]
        assert row["method"] == "slot_extractor"
        assert row["intents"][0]["intent"] == "order_query"
        assert row["arbitration_reason"] == "slot_extractor_single_complete"
        assert [c["layer"] for c in row["candidates"]] == ["slot_extractor"]
        assert result["intents"][0]["intent"] == "order_query"

    def test_no_skill_package_still_single_row(self, monkeypatch):
        """skills 导入失败(未移植场景)时 fast-track 让位,同样单点落库。"""
        import builtins

        _wire_common(monkeypatch)
        calls = _record_logs(monkeypatch)
        real_import = builtins.__import__

        def _no_skills_import(name, *args, **kwargs):
            if name.endswith(".skills") or name == "..skills":
                raise ImportError("no skills package")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_skills_import)
        asyncio.run(IntentTriageEngine.process(_order_query_state()))
        assert len(calls) == 1 and calls[0]["method"] == "slot_extractor"


class TestIntentLogColumns:
    """三列真实落库(密封 PG,Alembic 0007 schema)。"""

    def test_persists_candidates_winner_reason(self, pg_factory):
        async def _run() -> IntentLog:
            async with get_session() as session:
                session.add(Thread(id="thread_arbit_db", business_id="ecommerce"))
                await session.commit()
            await IntentTriageEngine.log_intent_to_db(
                "thread_arbit_db",
                "退货政策是什么",
                [{"intent": "general_query", "confidence": 0.9}],
                "consult_no_rag",
                0.9,
                candidates=[{"layer": "consult_gate", "intent": "consult", "confidence": None}],
                arbitration_reason="consult_no_rag",
            )
            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            select(IntentLog).where(IntentLog.thread_id == "thread_arbit_db")
                        )
                    )
                    .scalars()
                    .all()
                )
                return rows[0]

        row = asyncio.run(_run())
        assert row.winner == "general_query"
        assert row.arbitration_reason == "consult_no_rag"
        assert row.candidates == [{"layer": "consult_gate", "intent": "consult", "confidence": None}]


class TestNodeAttribution:
    """bind_llm_call_node 兜底:无 langgraph_node 元数据的节点内直调不再落空白 node。"""

    @pytest.fixture(autouse=True)
    def _reset_call_context(self):
        yield
        # ContextVar 复位,防跨测试串味(顺带清 node 字段)
        bind_llm_call_context(thread_id=None, business_id=None)

    @staticmethod
    def _response() -> SimpleNamespace:
        message = SimpleNamespace(
            usage_metadata={"input_tokens": 10, "output_tokens": 5},
            response_metadata={"model_name": "glm-4.7"},
        )
        generation = SimpleNamespace(message=message)
        return SimpleNamespace(generations=[[generation]])

    def _capture_row(self, monkeypatch, run_id: uuid.UUID, metadata: dict | None) -> dict:
        rows: list[dict] = []

        async def _fake_persist(row: dict) -> None:
            rows.append(row)

        monkeypatch.setattr(telemetry, "_persist", _fake_persist)
        handler = LlmCallTelemetryHandler()
        start_kwargs = {"metadata": metadata} if metadata is not None else {}

        async def _drive() -> dict:
            handler.on_llm_start(serialized={}, prompts=["x"], run_id=run_id, **start_kwargs)
            await handler.on_llm_end(self._response(), run_id=run_id)
            # on_llm_end 内 create_task 的落盘任务需要让出事件循环一拍才会跑
            await asyncio.sleep(0.01)
            return rows[0]

        return asyncio.run(_drive())

    def test_contextvar_fills_blank_node(self, monkeypatch):
        bind_llm_call_context(thread_id="t_attr", business_id="ecommerce")
        bind_llm_call_node("triage")
        row = self._capture_row(monkeypatch, uuid.uuid4(), None)
        assert row["node"] == "triage", "无 langgraph_node 元数据时 node 取自 ContextVar"
        assert row["thread_id"] == "t_attr"

    def test_metadata_wins_over_contextvar(self, monkeypatch):
        bind_llm_call_context(thread_id="t_attr", business_id="ecommerce")
        bind_llm_call_node("triage")
        row = self._capture_row(monkeypatch, uuid.uuid4(), {"langgraph_node": "planner"})
        assert row["node"] == "planner", "元数据存在时优先(嵌套 Runnable 传播真值)"


if __name__ == "__main__":
    pytest.main([__file__])
