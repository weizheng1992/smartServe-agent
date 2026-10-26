#!/usr/bin/env python3
"""answerQuality judge 人工复判包构建器(eval-gap-2026-10 05 号票)。

流程:跑 judge-calibration.yaml(真引擎,answerQuality judge 打分)→ 解析逐例
(judge score/reason + 引擎回复)→ 渲染 calibration_sheet.md 人工复判表(每例
一列「人工:同意 / 不同意 + 一句理由」)。人填完后 tabulate.py 统计一致率。

用法(仓库根):
    PROMPTFOO_PYTHON=$PWD/services/.venv/bin/python \
      python3 eval/judge_calibration/build_package.py [--runs 2]

一致率口径(MT-Bench 律):judge-人一致 ≥80% 才可用;<80% 收紧 rubric 后重测。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).resolve().parents[1] / "judge-calibration.yaml"


def _is_judge_component(c: dict) -> bool:
    """judge 分量识别:promptfoo -o json 不携带断言元数据(实测 assertion 为空),
    以判别特征代替 —— 连续分值(rule 断言只有 0/1)或长 rubric 理由文本。"""
    score = c.get("score")
    if isinstance(score, (int, float)) and score not in (0, 1):
        return True
    reason = str(c.get("reason") or "")
    return len(reason) > 80 and any(k in reason for k in ("中文", "礼貌", "幻觉", "SOP", "维度", "回复"))


def _run_once(tag: str) -> list[dict]:
    out = Path(tempfile.gettempdir()) / f"judge-calib-{tag}.json"
    env_prefix = ["env", f"PROMPTFOO_PYTHON={REPO}/services/.venv/bin/python"]
    cmd = [
        *env_prefix, "bunx", "promptfoo", "eval", "-c", str(CONFIG),
        "-o", str(out), "--no-write", "--no-cache", "--no-table", "--delay", "3000",
    ]
    print(f"[calib] 跑第 {tag} 轮: {' '.join(cmd[2:])}")
    res = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    # promptfoo exit 100 = 有一例失败(判分维度),但结果文件完好且 judge 判次
    # 照落 —— 退出码不作为否决条件,只看产物是否可解析(05 号票 v2 实弹:3/4
    # 轮被误毙只剩 9 判次)
    if not out.exists():
        print(res.stdout[-2000:])
        print(res.stderr[-2000:], file=sys.stderr)
        raise SystemExit(f"promptfoo 失败 exit={res.returncode}:无产物文件")
    raw = json.loads(out.read_text())
    results = raw["results"] if isinstance(raw.get("results"), list) else raw["results"]["results"]
    rows = []
    for r in results:
        gr = r.get("gradingResult") or {}
        comps = gr.get("componentResults") or [gr]
        judge = next((c for c in comps if _is_judge_component(c)), None)
        if judge is None:
            continue  # 非 judge 断言的行
        desc = r.get("description") or (r.get("testCase") or {}).get("description") or ""
        vars_ = ((r.get("testCase") or {}).get("vars") or {})
        rows.append({
            "run": tag,
            "description": desc,
            "input": str(vars_.get("input") or "")[:120],
            "judge_pass": bool(judge.get("pass")),
            "judge_score": judge.get("score"),
            "judge_reason": str(judge.get("reason") or "")[:600],
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=4, help="跑几轮(默认 4:judge 治下用例约 9 例/轮,4 轮 ≈ 36 判次达标)")
    args = ap.parse_args()

    all_rows: list[dict] = []
    failed_runs = 0
    for i in range(1, args.runs + 1):
        try:
            all_rows.extend(_run_once(str(i)))
        except SystemExit as err:
            # 单轮偶发红(judge 方差例)不应炸掉整包 —— 已产出的轮次照收,
            # 失败轮记数如实呈现(判次不足时人工可补跑)
            failed_runs += 1
            print(f"[calib] 第 {i} 轮失败({err}),跳过")
    if failed_runs:
        print(f"[calib] ⚠ {failed_runs}/{args.runs} 轮失败,判次按成功轮计")

    sheet = Path(__file__).resolve().parent / "calibration_sheet.md"
    lines = [
        "# answerQuality judge 人工复判表(05 号票)",
        "",
        f"生成判次:{len(all_rows)}(runs={args.runs})。填写规则:每例在「人工」列填",
        "`同意`(judge 判得对)或 `不同意:一句理由`。全部填完跑 tabulate.py 得一致率。",
        "口径:一致率 ≥80% judge 可用;<80% 收紧 rubric 后重测。",
        "",
    ]
    for i, r in enumerate(all_rows, 1):
        lines += [
            f"## #{i} [run{r['run']}] {r['description']}",
            "",
            f"- **问句**: {r['input']}",
            f"- **judge**: pass={r['judge_pass']} score={r['judge_score']}",
            f"- **judge 理由**: {r['judge_reason']}",
            "- **人工**: ",
            "",
        ]
    sheet.write_text("\n".join(lines), encoding="utf-8")
    print(f"[calib] 复判表已生成: {sheet}(共 {len(all_rows)} 判次)")


if __name__ == "__main__":
    main()
