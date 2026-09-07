"""promptfoo 结果入库(wayfinder 005)— 死表接通:eval_runs/eval_results +
admin 展示汇总行,密封 PG 钉死三表同事务落盘与两代 JSON 形状兼容。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import select

from engine_py.db import EvalResult, EvalRun, EvalRunRecordRow, get_session
from engine_py.evals.promptfoo_import import import_file, load_summary

pytestmark = pytest.mark.usefixtures("pg_factory")

# 0.111.x 形状:-o json 外层 {evalId, results: {results: [...], stats}, ...}
MODERN_SHAPE = {
    "evalId": "eval-abc123",
    "results": {
        "results": [
            {
                "testIdx": 0,
                "testCase": {"description": "退款意图直达"},
                "success": True,
                "score": 1,
                "latencyMs": 812.5,
                "tokenUsage": {"total": 1500},
            },
            {
                "testIdx": 1,
                "testCase": {"description": "多意图拆单"},
                "success": False,
                "score": 0,
                "error": "expected tools mismatch",
                "latencyMs": 1200.0,
                "tokenUsage": {"total": 2500},
            },
        ],
        "stats": {"successes": 1, "failures": 1, "errors": 0},
    },
    "config": {},
}

# 旧版形状:逐行 results 数组与 stats 在根级
LEGACY_SHAPE = {
    "results": [
        {"testIdx": 0, "description": "根级用例", "success": True, "score": 0.9},
    ],
    "stats": {"successes": 1, "failures": 0, "errors": 0},
}


def _write(path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_load_summary_兼容两代形状(tmp_path):
    modern, modern_stats = load_summary(_dump(tmp_path / "unified.json", MODERN_SHAPE))
    assert len(modern) == 2
    assert modern_stats["successes"] == 1

    legacy, legacy_stats = load_summary(_dump(tmp_path / "legacy.json", LEGACY_SHAPE))
    assert len(legacy) == 1
    assert legacy_stats["failures"] == 0


def _dump(path, payload) -> object:
    _write(path, payload)
    return path


async def _fetch_artifacts(run_id: str) -> tuple:
    """按 run_id 取回三表落盘产物(eval_runs 行 / eval_results 行 / 展示汇总行)。"""
    parsed = uuid.UUID(run_id)  # eval_runs 主键为 UUID
    async with get_session() as session:
        run = (
            await session.execute(select(EvalRun).where(EvalRun.id == parsed))
        ).scalar_one()
        cases = list(
            (
                await session.execute(select(EvalResult).where(EvalResult.run_id == parsed))
            ).scalars()
        )
        summary = (
            await session.execute(
                select(EvalRunRecordRow).where(EvalRunRecordRow.id == f"eval_run_{run_id}")
            )
        ).scalar_one()
        return run, cases, summary


def test_导入落盘三表且口径映射正确(tmp_path):
    path = _dump(tmp_path / "unified.json", MODERN_SHAPE)

    run_id = asyncio.run(import_file(path))

    run, cases, summary = asyncio.run(_fetch_artifacts(run_id))

    # eval_runs:通过率 / 均分 / 延迟 / token 成本($0.15/M,与 session_metrics 同口径)
    assert run.pass_rate == 0.5
    assert run.avg_answer_quality == 0.5
    assert run.avg_latency_ms == pytest.approx(1006.3, abs=0.1)
    assert run.total_cost_usd == pytest.approx(4000 / 1_000_000 * 0.15)
    assert run.business_id == "platform"
    assert run.git_commit and run.git_commit != "unknown"  # 仓库内运行可取到真实提交

    # eval_results:逐用例一行,失败用例携带 error 截断
    assert len(cases) == 2
    by_name = {c.case_name: c for c in cases}
    assert by_name["退款意图直达"].passed is True
    assert by_name["退款意图直达"].metrics["latencyMs"] == 812.5
    assert by_name["多意图拆单"].passed is False
    assert by_name["多意图拆单"].metrics["error"] == "expected tools mismatch"

    # eval_run_records:admin 展示汇总行(DTO 口径映射)
    assert summary.dataset_name == "unified"
    assert summary.sample_count == 2
    assert summary.tool_accuracy == 0.5  # ← pass_rate
    assert summary.rag_faithfulness == 0.5  # ← scorer 均分
    assert summary.hitl_trigger_rate == 0.0  # 套件不触达 HITL,诚实置零
    assert summary.run_name.startswith("promptfoo unified @ ")
    assert summary.status == "completed"


def test_旧版根级形状同样可导入(tmp_path):
    path = _dump(tmp_path / "classify.json", LEGACY_SHAPE)

    run_id = asyncio.run(import_file(path))

    run, _cases, summary = asyncio.run(_fetch_artifacts(run_id))
    assert run.pass_rate == 1.0
    assert run.avg_latency_ms is None  # 无 latencyMs 字段,置空不造数
    assert run.total_cost_usd == 0.0
    assert summary.dataset_name == "classify"
    assert summary.run_name.startswith("promptfoo classify @ ")


def test_非结果文件拒绝导入(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="缺少 results 数组"):
        asyncio.run(import_file(bad))


def test_空用例文件拒绝导入(tmp_path):
    empty = _dump(tmp_path / "empty.json", {"results": []})
    with pytest.raises(ValueError, match="无任何用例"):
        asyncio.run(import_file(empty))


def test_CLI模块入口导入并落盘(tmp_path):
    """`python -m engine_py.evals.promptfoo_import` 端到端:钉死 __main__ 入口
    (缺失该守卫时模块被静默导入、exit 0 无输出,bun 链路因此零入库)。"""
    path = _dump(tmp_path / "cli.json", MODERN_SHAPE)
    res = subprocess.run(
        [sys.executable, "-m", "engine_py.evals.promptfoo_import", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,  # 退出码由断言钉死
    )
    assert res.returncode == 0, res.stderr
    assert "导入成功: cli.json" in res.stdout

    async def _summary_rows():
        async with get_session() as session:
            return list(
                (
                    await session.execute(
                        select(EvalRunRecordRow).where(EvalRunRecordRow.dataset_name == "cli")
                    )
                ).scalars()
            )

    assert len(asyncio.run(_summary_rows())) == 1
