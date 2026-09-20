"""SemQL SFT 数据集构建(用户最新文档路线:模型只学语义理解,输出 SemQL)。

训练样本格式(与提案一致)::

    用户问题 + 指标字典片段 → SemQL(结构化语义查询 JSON,不含物理表名)

- 问句:同义词 × 时间窗 × 品类 × limit 组合生成(词面与 L0 解析规则一致,
  保证「问句字面 ↔ SemQL 槽位」可校验);
- 输出:StructuredQueryIntent 兼容 JSON(metric/direction/limit/time_window/category);
- 不变量(18 号):评测集纯门永不入训 —— mapping.json 的 input 精确排除。

用法(services/engine-py 下)::

    uv run python scripts/training/sft_dataset.py \\
        --out training_data/sft/train.jsonl \\
        --eval ../../eval/testCases/data_analytics/mapping.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY

_TIME_VARIANTS = [
    (None, ""),
    ({"kind": "last_7d"}, "近 7 天"),
    ({"kind": "last_30d"}, "近 30 天"),
    ({"kind": "last_month"}, "上个月"),
]
_CATEGORIES = ["户外机能", "潮流T恤", "下装裤类", "潮流鞋靴", "背包收纳", "露营装备", "衬衫", "配饰", "运动配件"]
_LIMITS = [None, 10, 20]


def _system_prompt() -> str:
    lines = []
    for key, m in METRIC_SEMANTIC_REGISTRY.items():
        if key == "order_overview":
            continue
        lines.append(f"- {key}({m['label']}): {m['description'][:50]}")
    return (
        "你是商户数据问答的意图解析器。把用户问题解析为 JSON:"
        '{"metric": 指标key, "direction": "ASC"|"DESC", "limit": 整数或null, '
        '"time_window": {"kind": "last_7d"|"last_30d"|"last_month"} 或 null, '
        '"category": 品类或null}。\n指标闭集:\n' + "\n".join(lines)
    )


def build_sft_rows(
    registry: dict | None = None,
    eval_inputs: set[str] | frozenset[str] = frozenset(),
    system_prompt: str | None = None,
) -> list[dict[str, str]]:
    """词表 × 槽位组合生成 SFT 样本;评测集输入精确排除(纯门不入训)。"""
    registry = registry or METRIC_SEMANTIC_REGISTRY
    catalog = system_prompt if system_prompt is not None else _system_prompt()
    rows: list[dict[str, str]] = []
    for key, metric in registry.items():
        if key == "order_overview":
            continue  # order_overview 无词面变体,文末专属问法单独加
        seen: set[str] = set()

        def add(question: str, metric_key: str = key, seen_set: set[str] = seen) -> None:
            q = question.strip()
            if not q or q in seen_set or q in eval_inputs:
                return
            seen_set.add(q)
            semql = _semql_for(registry, metric_key, q)
            rows.append({
                "instruction": catalog,
                "input": q,
                "output": json.dumps(semql, ensure_ascii=False),
                "_metric": metric_key,
            })

        phrases = [metric["label"], *(metric.get("synonyms") or [])]
        for phrase in phrases:
            add(phrase)
            for _, tw_word in _TIME_VARIANTS[1:]:
                add(f"{tw_word}{phrase}")
            for cat in _CATEGORIES:
                add(f"{cat}{phrase}")
            # 同义词条目直接解析为该 limit 值(声明口径:同义词×时间窗×品类×limit 全组合)
            for lim in _LIMITS[1:]:
                add(f"{phrase} Top {lim}")
            # 时间窗 × 品类 交叉组合(60b74cc 声明的覆盖面,此前缺失)
            for _, tw_word in _TIME_VARIANTS[1:]:
                for cat in _CATEGORIES:
                    add(f"{tw_word}{cat}{phrase}")
        # 反向变体(与 L0 反向词族一致)
        for phrase in phrases[:2]:
            add(f"{phrase}最低")
    # order_overview 专属(勾选/选中问法)
    prompt = _system_prompt()
    for q in ("勾选订单的统计", "选中订单的概览", "所选订单"):
        if q not in eval_inputs:
            add_order_overview(rows, q, prompt)
    return rows


def add_order_overview(rows: list[dict[str, str]], q: str, system_prompt: str) -> None:
    semql = {"metric": "order_overview", "direction": "DESC", "limit": None,
             "time_window": None, "category": None}
    rows.append({
        "instruction": system_prompt,
        "input": q,
        "output": json.dumps(semql, ensure_ascii=False),
        "_metric": "order_overview",
    })


def _semql_for(registry: dict, metric_key: str, question: str) -> dict:
    """问句 → SemQL(与 L0 词面规则一致,用于构造自洽训练样本)。"""
    metric = registry[metric_key]
    reverse = any(w in question for w in ("最差", "垫底", "最烂", "卖不动", "不走量", "最低", "最少"))
    direction = ("ASC" if metric["direction"] == "DESC" else "DESC") if reverse else metric["direction"]
    m_lim = re.search(r"top\s*(\d+)", question, re.IGNORECASE)
    limit = int(m_lim.group(1)) if m_lim else 5
    tw = None
    for kind, pat in (("last_7d", r"近\s*7\s*天"), ("last_30d", r"近\s*30\s*天"), ("last_month", r"上个月|上月")):
        if re.search(pat, question):
            tw = {"kind": kind}
            break
    cat = None
    m = re.search(r"(户外机能|潮流T恤|下装裤类|潮流鞋靴|背包收纳|露营装备|衬衫|配饰|运动配件)", question)
    if m:
        cat = m.group(1)
    return {"metric": metric_key, "direction": direction, "limit": limit,
            "time_window": tw, "category": cat}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SemQL SFT 数据集构建")
    parser.add_argument("--out", default="training_data/sft/train.jsonl")
    parser.add_argument("--eval", default="../../eval/testCases/data_analytics/mapping.json",
                        help="评测集(纯门永不入训:其 input 精确排除)")
    args = parser.parse_args(argv)

    eval_inputs: set[str] = set()
    eval_path = Path(args.eval)
    if eval_path.exists():
        for e in json.loads(eval_path.read_text(encoding="utf-8")):
            q = (e.get("vars") or {}).get("input")
            if q:
                eval_inputs.add(q)

    rows = build_sft_rows(eval_inputs=eval_inputs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"SFT 样本 {len(rows)} 条 → {out}(评测集输入已排除)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
