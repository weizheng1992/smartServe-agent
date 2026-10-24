"""步级执行日志与崩溃恢复(docs/multi-turn-task-state.md P2-1,2026-10-24 D5)。

三层缝:纯函数(rebuild/plan_to_persist 落库策略)→ 密封 PG(写 diff 与
崩溃尾巴检测)→ planner Journal-Resume 保留分支(门禁钉死)。全程旁路自吞
纪律的验证含在内:写入失败不阻断、检测失败按无尾巴。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import select, text

from engine_py.db import TaskStepJournalRow, get_session
from engine_py.graph.nodes.planner import planner_node
from engine_py.memory.step_journal import (
    detect_crash_tail,
    plan_to_persist_on_crash,
    rebuild_plan_from_journal,
    write_step_transitions,
)

# ── 纯函数:rebuild_plan_from_journal(无 DB 依赖,不挂 pg_factory)──────


def _plan() -> dict:
    return {
        "goal": "上海行程",
        "currentStepIndex": 0,
        "subtasks": [
            {"id": "s1", "description": "查高铁", "status": "pending"},
            {"id": "s2", "description": "订酒店", "status": "pending"},
            {"id": "s3", "description": "订会议", "status": "pending"},
        ],
    }


class TestRebuildPlanFromJournal:
    def test_completed_kept_failed_retried(self):
        rows = [
            {"step_index": 0, "status": "completed"},
            {"step_index": 1, "status": "failed"},
        ]
        out = rebuild_plan_from_journal(_plan(), rows)
        assert out["subtasks"][0]["status"] == "completed"
        assert out["subtasks"][1]["status"] == "failed", "失败步挂回重试"
        assert out["currentStepIndex"] == 1, "落在首个未完成步(失败步本身)"

    def test_failed_before_completed_coexist_not_skipped(self):
        """并行分支实态:failed 步先于 completed 步共存 —— currentStepIndex 取
        「首个未完成」而非 max(completed)+1,失败步严禁被索引跳过(code-review
        裁定);已 completed 的后继步由执行器自然跳过。"""
        rows = [
            {"step_index": 0, "status": "completed"},
            {"step_index": 1, "status": "failed"},
            {"step_index": 2, "status": "completed"},
        ]
        out = rebuild_plan_from_journal(_plan(), rows)
        assert out["subtasks"][1]["status"] == "failed"
        assert out["subtasks"][2]["status"] == "completed"
        assert out["currentStepIndex"] == 1

    def test_later_row_wins_same_step(self):
        """同 idx 补写(failed→completed)后写真值 last-wins(detect 已按
        (step_index, created_at) 排序)。"""
        rows = [
            {"step_index": 0, "status": "failed"},
            {"step_index": 0, "status": "completed"},
        ]
        out = rebuild_plan_from_journal(_plan(), rows)
        assert out["subtasks"][0]["status"] == "completed"
        assert out["currentStepIndex"] == 1

    def test_all_completed_lands_at_end(self):
        rows = [{"step_index": i, "status": "completed"} for i in range(3)]
        out = rebuild_plan_from_journal(_plan(), rows)
        assert out["currentStepIndex"] == 3, "全部完成 → 越界索引,执行器 subtask None 直通 finish"

    def test_failed_step_that_was_completed_gets_demoted(self):
        plan = _plan()
        plan["subtasks"][0]["status"] = "completed"
        out = rebuild_plan_from_journal(plan, [{"step_index": 0, "status": "failed"}])
        assert out["subtasks"][0]["status"] == "failed", "journal 真值压过计划内旧状态"
        assert out["currentStepIndex"] == 0

    def test_out_of_range_rows_ignored(self):
        out = rebuild_plan_from_journal(_plan(), [{"step_index": 99, "status": "completed"}, {"step_index": -1, "status": "ok"}])
        assert out["subtasks"][0]["status"] == "pending"
        assert out["currentStepIndex"] == 0

    def test_empty_rows_or_plan_passthrough(self):
        plan = _plan()
        assert rebuild_plan_from_journal(plan, []) is plan
        assert rebuild_plan_from_journal({"goal": "x"}, [{"step_index": 0, "status": "completed"}]) == {"goal": "x"}

    def test_source_plan_not_mutated(self):
        plan = _plan()
        rebuild_plan_from_journal(plan, [{"step_index": 0, "status": "completed"}])
        assert plan["subtasks"][0]["status"] == "pending", "纯函数不得原地改"


class TestPlanToPersistOnCrash:
    def test_crash_empty_result_keeps_saved_plan(self):
        saved = {"goal": "上海行程", "subtasks": [{"id": "s1"}], "currentStepIndex": 1}
        out = plan_to_persist_on_crash({"goal": "Multi-turn conversational assistance", "subtasks": []}, saved, crash=True)
        assert out["subtasks"] == [{"id": "s1"}] and out["currentStepIndex"] == 1
        assert "guideContext" not in out, "只挑计划三键,域总线键不混入"

    def test_crash_with_real_result_plan_uses_result(self):
        result_plan = {"goal": "g", "subtasks": [{"id": "s1", "status": "completed"}]}
        assert plan_to_persist_on_crash(result_plan, {"subtasks": [{"id": "old"}]}, crash=True) is result_plan

    def test_non_crash_passthrough(self):
        stub = {"goal": "", "subtasks": []}
        assert plan_to_persist_on_crash(stub, {"subtasks": [{"id": "s1"}]}, crash=False) is stub

    def test_crash_and_nothing_saved(self):
        stub = {"subtasks": []}
        assert plan_to_persist_on_crash(stub, None, crash=True) is stub


# ── 密封 PG:写 diff 与崩溃尾巴检测 ───────────────────────────────────


async def _seed_thread(thread_id: str) -> None:
    """task_step_journal/session_metrics 都对 threads 有 FK,先播种线程行。"""
    async with get_session() as session:
        await session.execute(
            text(
                'INSERT INTO threads (id, "user_id", business_id, status) '
                "VALUES (:t, 'u_step_journal', 'ecommerce', 'active') ON CONFLICT (id) DO NOTHING"
            ).bindparams(t=thread_id)
        )
        await session.commit()


async def _seed_metrics(thread_id: str, job_id: str, resolution_status: str) -> None:
    await _seed_thread(thread_id)
    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO session_metrics (business_id, thread_id, total_tokens, "
                "calculated_cost_usd, resolution_status, avg_latency_ms, job_id, turn_path) "
                "VALUES ('ecommerce', :t, 0, 0, :rs, 0, :j, 'deep_path')"
            ).bindparams(t=thread_id, rs=resolution_status, j=job_id)
        )
        await session.commit()


async def _journal_rows(job_id: str) -> list[TaskStepJournalRow]:
    async with get_session() as session:
        rows = (
            await session.execute(
                select(TaskStepJournalRow).where(TaskStepJournalRow.job_id == job_id).order_by(TaskStepJournalRow.step_index)
            )
        ).scalars().all()
        return list(rows)


@pytest.mark.usefixtures("pg_factory")
class TestWriteAndDetect:
    def test_write_diff_inserts_only_transitions(self):
        tid, job = f"tj_{uuid.uuid4().hex[:8]}", f"job_{uuid.uuid4().hex[:8]}"
        asyncio.run(_seed_thread(tid))
        prev = [{"id": "s1", "status": "pending"}, {"id": "s2", "status": "pending"}, {"id": "s3", "status": "completed"}]
        nxt = [
            {"id": "s1", "status": "completed", "result": {"summary": "查完高铁"}},
            {"id": "s2", "status": "failed"},
            {"id": "s3", "status": "completed"},  # 状态未变,不写
        ]
        n = asyncio.run(write_step_transitions(tid, job, prev, nxt))
        assert n == 2
        rows = asyncio.run(_journal_rows(job))
        assert [(r.step_index, r.status) for r in rows] == [(0, "completed"), (1, "failed")]
        assert rows[0].result_digest, "completed 步带结果指纹留痕"

    def test_write_no_op_and_missing_identity(self):
        assert asyncio.run(write_step_transitions("t", "j", [{"status": "pending"}], [{"status": "pending"}])) == 0
        assert asyncio.run(write_step_transitions("", "", [], [{"status": "completed"}])) == 0

    def test_detect_crash_tail_happy_path(self):
        tid, job = f"tj_{uuid.uuid4().hex[:8]}", f"job_{uuid.uuid4().hex[:8]}"
        asyncio.run(_seed_metrics(tid, job, "graph_error_degraded"))
        asyncio.run(write_step_transitions(tid, job, [{"status": "pending"}], [{"status": "completed"}]))
        tail = asyncio.run(detect_crash_tail(tid))
        assert tail is not None and tail["job_id"] == job
        assert tail["rows"] == [{"step_index": 0, "status": "completed"}]

    def test_detect_none_when_latest_turn_healthy(self):
        """超 1 轮未续由构造成立:崩溃后任何更新一轮(成功态)都让 latest 不再是崩溃 job。"""
        tid = f"tj_{uuid.uuid4().hex[:8]}"
        asyncio.run(_seed_metrics(tid, f"job_{uuid.uuid4().hex[:6]}", "graph_error_degraded"))
        asyncio.run(_seed_metrics(tid, f"job_{uuid.uuid4().hex[:6]}", "resolved_auto"))
        assert asyncio.run(detect_crash_tail(tid)) is None

    def test_detect_none_when_no_journal_rows(self):
        """崩溃但零步级行(计划未开跑即崩)→ 无恢复面,不载回。"""
        tid = f"tj_{uuid.uuid4().hex[:8]}"
        asyncio.run(_seed_metrics(tid, f"job_{uuid.uuid4().hex[:6]}", "llm_circuit_breaker"))
        assert asyncio.run(detect_crash_tail(tid)) is None

    def test_detect_none_for_unknown_thread(self):
        assert asyncio.run(detect_crash_tail(f"tj_none_{uuid.uuid4().hex[:6]}")) is None


# ── planner Journal-Resume 保留分支(桩夹具沿 hot-resume 套件惯例)──────


@contextmanager
def _fake_planner_llm(content: str | None = None):
    from engine_py.graph.nodes import planner as pl

    calls: list[str] = []

    class _Bound:
        async def ainvoke(self, prompt: str):
            calls.append(prompt)
            return type("Resp", (), {"content": content})()

    class _Model:
        def bind(self, **_kwargs) -> _Bound:
            return _Bound()

    original = pl.get_chat_model
    pl.get_chat_model = lambda: _Model()
    try:
        yield calls
    finally:
        pl.get_chat_model = original


def _state(**kwargs) -> dict:
    base = {"intents": [], "input": "", "short_memory": [{"role": "user", "content": "你好"}]}
    base.update(kwargs)
    return base


def _in_flight_plan() -> dict:
    return {
        "goal": "上海行程",
        "currentStepIndex": 1,
        "subtasks": [
            {"id": "s1", "description": "查高铁", "status": "completed"},
            {"id": "s2", "description": "订酒店", "status": "pending"},
        ],
    }


class TestPlannerJournalResume:
    def test_journal_resume_preserves_plan_zero_llm(self):
        prior = _in_flight_plan()
        with _fake_planner_llm("must not be called") as calls:
            result = asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "cart_manage", "confidence": 0.9}],
                        input="继续",
                        task_plan=prior,
                        journal_resume=True,
                        thread_id="t-jr",
                    )
                )
            )
        assert result["task_plan"] is prior, "Journal-Resume 必须原对象复用在途计划"
        assert result["global_transitions_count"] == 1
        assert calls == [], "崩溃恢复保留分支不得消耗 LLM"

    def test_journal_resume_skipped_on_system_resume(self):
        """System: 轮 HITL 语义优先(journal_resume 只在非 System 轮置位,双保险)。"""
        prior = _in_flight_plan()
        with _fake_planner_llm(None) as calls:
            asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "refund", "confidence": 0.9}],
                        input="System: Resume.",
                        task_plan=prior,
                        journal_resume=True,
                        thread_id="t-jr-sys",
                    )
                )
            )
        assert len(calls) == 1, "System 轮严禁被 Journal-Resume 抢道"

    def test_journal_resume_skipped_when_step_waiting_approval(self):
        """当前步挂审批 → 决议语义优先,严禁跳过审批通道。"""
        prior = _in_flight_plan()
        prior["subtasks"][1]["result"] = {"waitingForApproval": True, "approvalId": "a1"}
        with _fake_planner_llm(None) as calls:
            asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "refund", "confidence": 0.9}],
                        input="继续",
                        task_plan=prior,
                        journal_resume=True,
                        thread_id="t-jr-wait",
                    )
                )
            )
        assert len(calls) == 1

    def test_no_flag_no_preserve(self):
        """无恢复旗标(检测旁路判定无尾巴)→ 现状行为,严禁误保留。"""
        prior = _in_flight_plan()
        with _fake_planner_llm(None) as calls:
            asyncio.run(
                planner_node(
                    _state(
                        intents=[{"intent": "refund", "confidence": 0.9}],
                        input="随便问问",
                        task_plan=prior,
                        thread_id="t-jr-off",
                    )
                )
            )
        assert len(calls) == 1


if __name__ == "__main__":
    pytest.main([__file__])
