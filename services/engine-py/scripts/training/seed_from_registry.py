"""从 metric_registry 词表自动造弱标注种子(03/06 号文档路径:词表→弱标注)。

每条 synonyms/label/sampleQuery 生成同标签问句;另造反向词变体(direction
翻转语义由推理侧 L0 处理,训练分布只学「词面→指标键」)。输出 JSONL:
{query, label, source}。

用法(在 services/engine-py 下)::

    uv run python scripts/training/seed_from_registry.py --out training_data/metric_head/seed.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY

_TEMPLATES = [
    "{w}", "帮我看看{w}", "{w}的商品排行", "哪些商品{w}", "查一下{w}",
    "{w}有哪些", "统计{w}的商品", "{w}情况如何",
]
_REVERSE_TEMPLATES = ["{w}最低", "{w}最差", "{w}垫底的商品"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="词表→弱标注种子生成")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    rows: list[dict] = []
    for key, metric in METRIC_SEMANTIC_REGISTRY.items():
        if key == "order_overview":
            continue  # 实体概览不进分类分布(依赖 PageContext 选择)
        seen: set[str] = set()

        def add(text: str, label_key: str = key, seen_set: set[str] = seen) -> None:
            t = text.strip()
            if t and t not in seen_set:
                seen_set.add(t)
                rows.append({"query": t, "label": label_key, "source": "registry_seed"})

        add(metric["label"])
        for syn in metric.get("synonyms") or []:
            add(syn)
            for tpl in _TEMPLATES[1:]:
                add(tpl.format(w=syn))
        for q in metric.get("sampleQueries") or []:
            add(q)
        if metric.get("direction") == "DESC":
            base = (metric.get("synonyms") or [key])[0]
            for tpl in _REVERSE_TEMPLATES:
                add(tpl.format(w=base))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    per_class: dict[str, int] = {}
    for r in rows:
        per_class[r["label"]] = per_class.get(r["label"], 0) + 1
    print(f"[Seed] {len(rows)} 句 → {out}")
    for k, v in sorted(per_class.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
