"""标注数据加工:去重 → 评测句近邻过滤 → train/held-out 分层切分 → 标签闭集校验。

11-D3 流水线第 1-4 步的确定性部分(LLM 预标见 prelabel.py,人工裁分歧在线下表单/
编辑器完成)。入口::

    uv run python scripts/training/prepare_data.py --config configs/metric_head.toml

配置读 [task].labels(闭集)、[data](输入/输出/切分比/评测 blocklist/近邻阈值)、
[model].encoder(hash 可离线跑;真跑用 bge)。输出 out_dir 下:

- train.jsonl / heldout.jsonl — 分层切分结果(带 split 字段溯源)
- stats.json — 各阶段计数与每类样本数(判断「够不够训」直接看这里)
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    classification_report,
    cosine_matrix,
    encode_texts,
    get_encoder,
    load_config,
    load_jsonl,
    write_jsonl,
)


def dedup_by_query(records: list[dict]) -> tuple[list[dict], int]:
    """按 query 精确去重(保留首条;06 号实证:86% 重复是评测重跑,不去重会污染分布)。"""
    seen: set[str] = set()
    out = []
    for r in records:
        q = (r.get("query") or "").strip()
        if q and q not in seen:
            seen.add(q)
            out.append(r)
    return out, len(records) - len(out)


def near_dup_filter(
    records: list[dict], blocklist_texts: list[str], encoder_name: str, threshold: float
) -> tuple[list[dict], int]:
    """评测句泄漏防护:与评测 blocklist 余弦 ≥ threshold 的训练句剔除(11-D3 cos≥0.90)。"""
    if not blocklist_texts or not records:
        return records, 0
    encoder = get_encoder(encoder_name)
    rec_vecs = encode_texts(encoder, [r["query"] for r in records])
    blk_vecs = encode_texts(encoder, blocklist_texts)
    sim = cosine_matrix(rec_vecs, blk_vecs).max(dim=1).values
    kept = [r for r, s in zip(records, sim.tolist(), strict=True) if s < threshold]
    return kept, len(records) - len(kept)


def stratified_split(records: list[dict], ratio: float, seed: int) -> tuple[list[dict], list[dict]]:
    """按标签分层切分;每类不足 2 条全部进 train(stats 会提示该类无法评估)。"""
    rng = random.Random(seed)
    by_label: dict[str, list[dict]] = {}
    for r in records:
        by_label.setdefault(r["label"], []).append(r)
    train, heldout = [], []
    for label in sorted(by_label):
        items = by_label[label]
        rng.shuffle(items)
        n_hold = round(len(items) * ratio) if len(items) >= 2 else 0
        heldout.extend(items[:n_hold])
        train.extend(items[n_hold:])
    return train, heldout


def validate_labels(records: list[dict], labels: list[str]) -> None:
    unknown = sorted({r["label"] for r in records} - set(labels))
    if unknown:
        raise SystemExit(f"[Prepare] 数据里存在闭集外标签 {unknown};闭集 = {labels}(改 [task].labels 或修数据)")


def _blocklist_texts(path: str | None, field: str) -> list[str]:
    """评测 blocklist 加载:支持 JSONL 与 promptfoo JSON 数组(点路径 field,如 vars.input)。"""
    if not path:
        return []
    import json as _json
    p = Path(path)
    if not p.exists():
        print(f"[Prepare] blocklist 文件不存在,跳过泄漏过滤: {path}")
        return []
    if p.suffix == ".json":
        raw = _json.loads(p.read_text(encoding="utf-8"))
    else:
        raw = [ _json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip() ]

    def _dig(r: dict, dotted: str):
        cur = r
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    out = []
    for r in raw:
        v = _dig(r, field) if "." in field else r.get(field)
        if v is None:
            v = r.get("query") or r.get("input")
        if v:
            out.append(str(v).strip())
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="训练数据加工:去重/近邻过滤/分层切分")
    parser.add_argument("--config", required=True, help="训练配置 TOML")
    parser.add_argument("--in", dest="in_jsonl", help="覆盖 [data].train_jsonl(如 prelabel 产物)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    task, data, model = cfg["task"], cfg["data"], cfg["model"]
    labels: list[str] = task["labels"]
    src = Path(args.in_jsonl or data["train_jsonl"])

    records = [{**r, "query": (r.get("query") or r.get("input_text") or "").strip(), "label": r.get("label") or r.get("intent")}
               for r in load_jsonl(src)]
    records = [r for r in records if r["query"] and r["label"]]
    validate_labels(records, labels)

    records, n_dup = dedup_by_query(records)
    records, n_leak = near_dup_filter(records, _blocklist_texts(data.get("eval_blocklist_jsonl"), data.get("blocklist_field", "query")),
                                      model["encoder"], data.get("near_dup_threshold", 0.90))
    rng_seed = cfg["train"].get("seed", 42)
    train, heldout = stratified_split(records, data.get("heldout_ratio", 0.15), rng_seed)
    for r in train:
        r["split"] = "train"
    for r in heldout:
        r["split"] = "heldout"

    out_dir = Path(data["out_dir"])
    write_jsonl(train, out_dir / "train.jsonl")
    write_jsonl(heldout, out_dir / "heldout.jsonl")
    label_idx = {lab: i for i, lab in enumerate(labels)}
    stats = {
        "source": str(src),
        "loaded": len(records) + n_dup + n_leak,
        "deduped_removed": n_dup,
        "near_dup_removed": n_leak,
        "train": len(train),
        "heldout": len(heldout),
        "per_class": {lab: sum(1 for r in records if r["label"] == lab) for lab in labels},
        "heldout_report": classification_report(
            [label_idx[r["label"]] for r in heldout], [label_idx[r["label"]] for r in heldout], labels
        ) if heldout else None,
        "labels": labels,
    }
    import json

    (out_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[Prepare] {src}: 去重-{n_dup} 近邻过滤-{n_leak} → train={len(train)} heldout={len(heldout)} → {out_dir}", file=sys.stderr)
    thin = [lab for lab, n in stats["per_class"].items() if n < 32]
    if thin:
        print(f"[Prepare] 提示:以下类别样本 <32(11-D2 门槛参考): {thin}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
