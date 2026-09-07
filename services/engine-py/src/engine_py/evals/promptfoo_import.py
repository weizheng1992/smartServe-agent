"""promptfoo 评测结果入库 — 接通死表 eval_runs / eval_results(wayfinder 005)。

真实评测由 promptfoo CLI 产出 JSON(``bun run test:prompt:record``),本模块
把结果文件导入库:
- ``eval_runs``:一次套件运行一行(通过率 / scorer 均分 / 平均延迟 / token
  成本 / git 提交);
- ``eval_results``:逐用例一行(通过与否 + 指标 JSONB);
- ``eval_run_records``:admin 评测页展示汇总行(口径映射见 ``_summary_record``;
  /api/evals/results 读该表,DTO 冻结)。

CLI:``uv run python -m engine_py.evals.promptfoo_import <结果.json|目录> [...]``
(目录导入其中全部 ``*.json``;npm 脚本 ``bun run evals:import`` 同义)。
文件名即套件名(unified / planner / classify,由 recordEvals.ts 落盘约定)。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from ..db import EvalResult, EvalRun, EvalRunRecordRow, get_session

# 与 session_metrics 成本换算同口径(observability §1.3:$0.15/M tokens)
COST_PER_M_TOKENS = 0.15
# promptfoo 套件为平台级回归,不归属单一租户
PLATFORM_BUSINESS_ID = "platform"


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()
    except Exception as err:
        print(f"[EvalsImport] git 提交号获取失败,降级 unknown: {err}")
        return "unknown"


def load_summary(path: Path) -> tuple[list[dict], dict]:
    """读取 promptfoo 输出 JSON,兼容 0.111.x 外层与旧版根级两种形状。

    0.111.x 起 ``-o json`` 外层为 ``{evalId, results: {results: [...], stats}, ...}``,
    旧版逐行 ``results`` 数组与 ``stats`` 在根级(与 eval/baselineLib.ts 归一同义)。
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"非 promptfoo 结果文件(根级非对象): {path}")  # noqa: TRY004 — 校验的是文件内容形状,非入参类型
    results = raw.get("results")
    stats = raw.get("stats") or {}
    if not isinstance(results, list) and isinstance(results, dict) and isinstance(results.get("results"), list):
        stats = results.get("stats") or stats
        results = results["results"]
    if not isinstance(results, list):
        raise ValueError(f"非 promptfoo 结果文件(缺少 results 数组): {path}")  # noqa: TRY004 — 同上,文件内容形状
    return results, stats


def _case_name(item: dict) -> str:
    """用例名:description 优先,0.111.x 挪入 testCase 的次之,兜底 testIdx。"""
    desc = item.get("description")
    if not desc:
        desc = (item.get("testCase") or {}).get("description")
    return str(desc or f"#{item.get('testIdx', '?')}")


def _summary_record(run: EvalRun, *, suite: str, total: int) -> EvalRunRecordRow:
    """admin 评测页展示行(eval_run_records,/api/evals/results 同表)。

    DTO 冻结(TS 基线),字段语义按最接近的真实指标映射:
    - tool_accuracy ← pass_rate(套件断言以工具调用/结构化输出为主);
    - rag_faithfulness ← avg_answer_quality(scorer 均分);
    - hitl_trigger_rate ← 0.0(promptfoo 套件不触达 HITL 链路,诚实置零)。
    """
    return EvalRunRecordRow(
        id=f"eval_run_{run.id}",
        run_name=f"promptfoo {suite} @ {run.git_commit[:8]}",
        dataset_name=suite,
        sample_count=total,
        tool_accuracy=run.pass_rate,
        rag_faithfulness=run.avg_answer_quality,
        hitl_trigger_rate=0.0,
        status="completed",
    )


async def import_file(path: Path, *, business_id: str = PLATFORM_BUSINESS_ID) -> str:
    """导入单个结果文件:eval_runs + 逐用例 eval_results + 展示汇总行,同事务。

    Returns: 新 eval_runs 行 ID(UUID 字符串)。
    """
    results, _stats = load_summary(path)
    total = len(results)
    if total == 0:
        raise ValueError(f"结果文件无任何用例: {path}")

    passed = sum(1 for r in results if r.get("success"))
    scores = [float(r.get("score") or 0) for r in results]
    latencies = [float(r["latencyMs"]) for r in results if isinstance(r.get("latencyMs"), (int, float))]
    tokens = sum(int((r.get("tokenUsage") or {}).get("total") or 0) for r in results)
    commit = _git_commit()
    suite = path.stem

    async with get_session() as session:
        run = EvalRun(
            business_id=business_id,
            git_commit=commit,
            avg_answer_quality=round(sum(scores) / total, 4),
            avg_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else None,
            total_cost_usd=round(tokens / 1_000_000 * COST_PER_M_TOKENS, 6),
            pass_rate=round(passed / total, 4),
        )
        session.add(run)
        await session.flush()  # 先取 run.id,逐用例行与汇总行都要引用

        for item in results:
            metrics: dict = {"score": float(item.get("score") or 0)}
            if isinstance(item.get("latencyMs"), (int, float)):
                metrics["latencyMs"] = float(item["latencyMs"])
            if item.get("error"):
                metrics["error"] = str(item["error"])[:500]
            session.add(
                EvalResult(
                    run_id=run.id,
                    case_name=_case_name(item),
                    passed=bool(item.get("success")),
                    metrics=metrics,
                )
            )

        session.add(_summary_record(run, suite=suite, total=total))
        await session.commit()
    return str(run.id)


async def _import_all(targets: list[Path]) -> int:
    failed = False
    for path in targets:
        try:
            run_id = await import_file(path)
            print(f"[EvalsImport] 导入成功: {path.name} → eval_runs/{run_id} (business={PLATFORM_BUSINESS_ID})")
        except Exception as err:
            failed = True
            print(f"[EvalsImport] 导入失败: {path.name}: {err}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("用法: python -m engine_py.evals.promptfoo_import <结果.json|目录> [...]")
        return 2

    targets: list[Path] = []
    for arg in args:
        path = Path(arg)
        if path.is_dir():
            targets.extend(sorted(path.glob("*.json")))
        elif path.is_file():
            targets.append(path)
        else:
            print(f"[EvalsImport] 路径不存在: {path}")
    if not targets:
        print("[EvalsImport] 未发现可导入的结果文件")
        return 2
    return asyncio.run(_import_all(targets))


if __name__ == "__main__":
    raise SystemExit(main())
