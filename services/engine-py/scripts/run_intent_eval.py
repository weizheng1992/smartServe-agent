"""意图解析评测跑分器(services/engine-py 下运行):

    AI_INTENT_L3=off uv run python scripts/run_intent_eval.py [--show-fails]

- 确定性评测:L3 关闭,只考察 L0 词面 / L2 范例 / 语义规则的解析质量;
- 主指标 = metric 路由准确率(≥95% 才算达标,否则退出码 1);
- 次指标 = 方向/时间窗/图型槽位命中率(报告,不设闸);
- expect_unsupported:闭集外问句必须响亮拒绝(08-P1)。

诚实原则:这份跑分就是词面/模板每次改动后的回归证据 —— 没有它,
调参是盲调。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# L3 关闭:评测确定性层(词面/范例/规则),不烧 token、不随模型漂移
os.environ.setdefault("AI_INTENT_L3", "off")

from engine_py.analytics.engine import MetricQueryEngine, UnsupportedQuery  # noqa: E402
from engine_py.analytics.graph import ask  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent.parent / "evals" / "intent_cases.jsonl"
PASS_THRESHOLD = 0.95


async def eval_case(case: dict, engine: MetricQueryEngine) -> dict:
    question = case["question"]
    out: dict = {"question": question, "expect_metric": case.get("expect_metric"), "ok": False, "got": None}
    try:
        intent = engine.resolve(question)
    except UnsupportedQuery:
        out["got"] = "unsupported"
        out["ok"] = bool(case.get("expect_unsupported"))
        return out
    if isinstance(intent, dict):  # 冲突反问(如「卖得最好」歧义)= 设计行为
        out["got"] = "clarify"
        out["ok"] = bool(case.get("expect_clarify")) or bool(case.get("expect_unsupported"))
        return out
    out["got"] = intent.metric
    out["ok"] = intent.metric == case.get("expect_metric")
    if out["ok"]:
        want_dir = case.get("expect_direction")
        if want_dir and intent.direction != want_dir:
            out["ok"] = False
            out["fail"] = f"direction {intent.direction} != {want_dir}"
        want_time = case.get("expect_time")
        if want_time and (intent.time_window or {}).get("kind") != want_time:
            out["ok"] = False
            out["fail"] = f"time {(intent.time_window or {}).get('kind')} != {want_time}"
        want_chart = case.get("expect_chart")
        if want_chart and intent.chart_hint != want_chart:
            out["ok"] = False
            out["fail"] = f"chart {intent.chart_hint} != {want_chart}"
    return out


async def main_async(show_fails: bool) -> int:
    cases = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    l3_cases = [c for c in cases if c.get("layer") == "L3"]
    cases = [c for c in cases if c.get("layer") != "L3"]
    engine = MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})
    results = []
    for case in cases:
        try:
            results.append(await eval_case(case, engine))
        except Exception as err:  # 解析器抛非 Unsupported 异常 = 硬失败
            results.append({"question": case["question"], "expect_metric": case.get("expect_metric"),
                            "ok": False, "got": f"EXCEPTION {type(err).__name__}: {err}"})

    metric_cases = [r for r, c in zip(results, cases) if not c.get("expect_unsupported")]
    unsup_cases = [r for r, c in zip(results, cases) if c.get("expect_unsupported")]
    metric_pass = sum(1 for r in metric_cases if r["ok"])
    unsup_pass = sum(1 for r in unsup_cases if r["ok"])
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    rate = passed / total if total else 0.0

    print(f"\n== 意图解析评测 ==\n用例 {total}(另 L3 层跳过 {len(l3_cases)}) | 通过 {passed} | 准确率 {rate:.1%}(闸门 {PASS_THRESHOLD:.0%})")
    print(f"应答面: {metric_pass}/{len(metric_cases)} | 拒绝面: {unsup_pass}/{len(unsup_cases)}")
    fails = [r for r in results if not r["ok"]]
    if fails:
        print("\n-- 失败清单 --")
        for r in fails:
            print(f"  ✗ {r['question'][:32]!r}  期望 {r.get('expect_metric')}  实得 {r['got']}"
                  + (f"({r.get('fail')})" if r.get("fail") else ""))
        if show_fails:
            for r in fails:
                print(json.dumps(r, ensure_ascii=False))
    if rate < PASS_THRESHOLD:
        print(f"\n✗ 未达标(< {PASS_THRESHOLD:.0%}),退出码 1")
        return 1
    print("\n✓ 达标")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-fails", action="store_true", help="JSON 形式输出失败明细")
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args.show_fails)))


if __name__ == "__main__":
    main()
