"""任务边界判定评测跑分器(docs/multi-turn-task-state.md P1-1,services/engine-py 下运行):

    AI_THINKING=disabled uv run python -m engine_py.evals.run_boundary_eval [--show-fails]

- 被测对象 = triage 结构化分类器的 boundary 字段(llm_refine 同一入口,
  与意图分类同源零额外调用 —— 裁决 D2);live LLM,30 例一轮;
- 评分口径:expect=modify/new → decision 命中且 confidence ≥ 阈值(下游会
  保留/重规划才算数);expect=clarify → confidence < 阈值或判定器弃权;
- 准确率 ≥ AI_BOUNDARY_EVAL_MIN(默认 0.8)退出码 0,否则 1。

诚实原则与 D6 看板先行纪律:本跑分是 boundary prompt/消费逻辑每次改动后的
回归证据;夜评硬闸由 AI_BOUNDARY_GATE 单独控制(默认 off,攒 2 周基线再开)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

EVAL_CASES_PATH = Path(__file__).resolve().parent / "boundary_cases.jsonl"


def load_boundary_cases(path: Path | None = None) -> list[dict]:
    """逐行 JSON 载入,空行/坏行跳过(评测集自身不许炸跑分器)。"""
    cases: list[dict] = []
    for line in (path or EVAL_CASES_PATH).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("input") and row.get("expect"):
            cases.append(row)
    return cases


def format_history(history: list[dict] | None, last_n: int = 6) -> str:
    """与 llm_refine 的 recent_history 同形(User/Assistant 行,截尾 N 条)。"""
    return "\n".join(
        f"{'User' if (m or {}).get('role') == 'user' else 'Assistant'}: {(m or {}).get('content')}"
        for m in (history or [])[-last_n:]
    )


def score_boundary_case(case: dict, boundary: dict | None, threshold: float) -> tuple[bool, str]:
    """单例评分(纯函数):返回 (是否通过, 实际判定摘要)。

    口径与被测行为一致(code-review 裁定):运行时判定器弃权(None)= 不澄清,
    所以 clarify 例的弃权同样算失败 —— 严禁"评分口径放水刷绿被测行为"。"""
    expect = case.get("expect")
    if boundary is None:
        # 弃权统一算失败:运行时 None = 不澄清不保留,任何 expect 都没被满足
        return False, "no-boundary(弃权)"
    try:
        conf = float(boundary.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    decision = str(boundary.get("decision") or "")
    if expect == "clarify":
        return (conf < threshold), f"{decision}@{conf:.2f}"
    ok = decision == expect and conf >= threshold
    return ok, f"{decision}@{conf:.2f}"


async def eval_one(case: dict, threshold: float) -> dict:
    """单例执行:classify(live LLM)→ 评分。异常计失败不炸整跑。"""
    from ..triage.structured_classifier import classify  # 延迟导入:env 就位后再拉起 config/LLM 链

    out: dict = {"input": case["input"], "expect": case.get("expect"), "ok": False, "got": None}
    try:
        res = await classify(case["input"], recent_history_text=format_history(case.get("history")))
        boundary = res.boundary.model_dump() if res.boundary is not None else None
        ok, got = score_boundary_case(case, boundary, threshold)
        out["ok"], out["got"] = ok, got
    except Exception as err:
        out["got"] = f"error: {err!r}"
    return out


async def main_async(show_fails: bool = True) -> int:
    from ..config import settings  # 延迟导入:main() 已先 load_env_file,settings 冻结时 env 就绪

    cases = load_boundary_cases()
    if not cases:
        print("[BoundaryEval] 评测集为空 —— 语料文件缺失/损坏即失败")
        return 1
    results = []
    for case in cases:
        results.append(await eval_one(case, settings.boundary_confidence_threshold))
    passed = sum(1 for r in results if r["ok"])
    accuracy = passed / len(results)
    print(f"[BoundaryEval] {passed}/{len(results)} = {accuracy:.2%}(闸 ≥ {os.environ.get('AI_BOUNDARY_EVAL_MIN', '0.8')})")
    if show_fails:
        for r in results:
            if not r["ok"]:
                print(f"  ✗ [{r['expect']}] {r['input']}  → {r['got']}")
    minimum = float(os.environ.get("AI_BOUNDARY_EVAL_MIN", "0.8"))
    return 0 if accuracy >= minimum else 1


def main() -> None:
    from ..intent_flywheel.common import load_env_file

    load_env_file()  # live LLM 需根 .env(badcase.cli 同律;缺 env 即 ConfigError 响亮拒绝)
    parser = argparse.ArgumentParser(description="任务边界判定评测(boundary 字段 live 跑分)")
    parser.add_argument("--show-fails", action="store_true", help="打印失败清单(默认开)")
    parser.add_argument("--no-show-fails", dest="show_fails", action="store_false")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(show_fails=args.show_fails)))


if __name__ == "__main__":
    main()
