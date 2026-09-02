"""影子对比 — 对双引擎回放结果 JSONL 逐会话比对(intents / tools / 规划步数)。

用法::

    python -m engine_py.shadow.diff --ts ts_results.jsonl --py py_results.jsonl

判定:
- intents 序列完全一致 → 意图等价
- tools 序列完全一致 → 规划-执行等价
- 输出文本不做逐字比对(LLM 非确定性),仅统计长度分布与健康度
"""

from __future__ import annotations

import argparse
import json


def _load(path: str) -> dict[str, dict]:
    records: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            records[record["threadId"]] = record
    return records


def diff_results(ts_path: str, py_path: str) -> dict:
    ts_records = _load(ts_path)
    py_records = _load(py_path)
    common = sorted(set(ts_records) & set(py_records))

    summary = {
        "tsTotal": len(ts_records),
        "pyTotal": len(py_records),
        "common": len(common),
        "intentMismatch": [],
        "toolMismatch": [],
        "errors": [],
    }

    for thread_id in common:
        ts_rec, py_rec = ts_records[thread_id], py_records[thread_id]
        if ts_rec.get("error") or py_rec.get("error"):
            summary["errors"].append(thread_id)
            continue
        ts_sig, py_sig = ts_rec["signature"], py_rec["signature"]
        if ts_sig["intents"] != py_sig["intents"]:
            summary["intentMismatch"].append({"threadId": thread_id, "ts": ts_sig["intents"], "py": py_sig["intents"]})
        if ts_sig["tools"] != py_sig["tools"]:
            summary["toolMismatch"].append({"threadId": thread_id, "ts": ts_sig["tools"], "py": py_sig["tools"]})

    compared = len(common) - len(summary["errors"])
    summary["intentMatchRate"] = (
        f"{(compared - len(summary['intentMismatch'])) / compared:.1%}" if compared else "n/a"
    )
    summary["toolMatchRate"] = f"{(compared - len(summary['toolMismatch'])) / compared:.1%}" if compared else "n/a"
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="engine-py 影子对比")
    parser.add_argument("--ts", required=True, help="TS 引擎回放结果 JSONL")
    parser.add_argument("--py", required=True, help="Python 引擎回放结果 JSONL")
    args = parser.parse_args()
    summary = diff_results(args.ts, args.py)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
