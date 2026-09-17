"""对任意 JSONL 评测一个训练 run(接入前的最后一步:heldout 之外的新数据复检)。

加载 run 目录的 head.pt + labels.json + config.snapshot.toml(encoder 名从快照读,
保证评测与训练同编码器),输出 accuracy / macro_f1 / 每类 P-R-F1,可选写 markdown
报告(贴进 11 号票的影子跑对比记录用)。

用法::

    uv run python scripts/training/evaluate.py --run-dir training_runs/metric_head \
        --data training_data/metric_head/heldout.jsonl [--out report.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import torch
from common import classification_report, encode_texts, get_encoder, load_config, load_jsonl
from torch import nn
from train import predict


def load_run(run_dir: str | Path) -> tuple[nn.Linear, list[str], dict]:
    run_dir = Path(run_dir)
    meta = json.loads((run_dir / "labels.json").read_text(encoding="utf-8"))
    labels: list[str] = meta["labels"]
    state = torch.load(run_dir / "head.pt", map_location="cpu")
    dim = state["weight"].shape[1]
    head = nn.Linear(dim, len(labels))
    head.load_state_dict(state)
    head.eval()
    cfg = load_config(run_dir / "config.snapshot.toml")
    return head, labels, cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="评测训练 run 对指定 JSONL 的表现")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--data", required=True, help="评测 JSONL(query + label 字段)")
    parser.add_argument("--label-field", default="label", help="标签字段名(缺省 label;评测旧数据可传 intent)")
    parser.add_argument("--out", help="可选 markdown 报告输出路径")
    args = parser.parse_args(argv)

    head, labels, cfg = load_run(args.run_dir)
    records = load_jsonl(args.data)
    texts = [r["query"] for r in records]
    y_true = [labels.index(r[args.label_field]) for r in records]

    encoder = get_encoder(cfg["model"]["encoder"])
    pred, _conf = predict(head, encode_texts(encoder, texts))
    report = classification_report(y_true, pred, labels)

    lines = [f"# 评测报告: {Path(args.run_dir).name} × {args.data}", "", f"- accuracy: **{report['accuracy']}**", f"- macro_f1: **{report['macro_f1']}**", "", "| 标签 | P | R | F1 | support |", "|---|---|---|---|---|"]
    for name, m in report["per_class"].items():
        lines.append(f"| {name} | {m['precision']} | {m['recall']} | {m['f1']} | {m['support']} |")
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"[Eval] 报告 → {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
