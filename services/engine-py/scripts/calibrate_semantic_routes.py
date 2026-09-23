"""语义路由阈值标定脚本(services/engine-py 下运行):

    uv run python scripts/calibrate_semantic_routes.py --cases evals/intent_cases.jsonl
    uv run python scripts/calibrate_semantic_routes.py --cases my_devset.jsonl --show-distribution

输入 JSONL 每行 {"text": "...", "intent": "promotion_query"}(text 键兼容
question)。对每条样本算与全部路由锚点的余弦,按意图聚合得分分布,遍历
候选阈值取最优 F1 —— 无跑分的调参是盲调(与 run_intent_eval 同纪律)。

输出:每意图 样本数/建议阈值/该阈值下 F1,以及与 semantic_routes.py 当前
阈值的差异提示。需要真实 embedding 模型(BGE 缓存或 AI_EMBEDDING_* 环境)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from engine_py.triage.semantic_cache import (
    SemanticVectorCache,
    cosine_similarity,
)
from engine_py.triage.semantic_routes import (
    SEMANTIC_ROUTES,
    SemanticIntentRouter,
)

CANDIDATE_THRESHOLDS = [round(0.70 + 0.01 * i, 2) for i in range(26)]  # 0.70~0.95


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, help="JSONL 路径,每行 {text|question, intent}")
    parser.add_argument("--show-distribution", action="store_true")
    args = parser.parse_args()

    cases: list[dict] = []
    with open(args.cases, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            text_value = item.get("text") or item.get("question") or ""
            intent = item.get("intent")
            if text_value and intent in SEMANTIC_ROUTES:
                cases.append({"text": text_value, "intent": intent})
    if not cases:
        print("没有可标定样本(需命中 SEMANTIC_ROUTES 中的意图)")
        return 1

    vectors = await SemanticIntentRouter.get_route_vectors()
    scored: dict[str, list[tuple[float, bool]]] = {intent: [] for intent in SEMANTIC_ROUTES}
    for case in cases:
        vector = await SemanticVectorCache.get_embedding_with_cache(case["text"])
        for intent in SEMANTIC_ROUTES:
            best = max(
                (cosine_similarity(vector, v) for v in vectors.get(intent, [])),
                default=0.0,
            )
            scored[intent].append((best, case["intent"] == intent))

    print(f"样本 {len(cases)} 条。建议阈值(按最优 F1):\n")
    for intent, samples in scored.items():
        pos = [s for s, label in samples if label]
        neg = [s for s, label in samples if not label]
        if not pos:
            print(f"  {intent}: 无正样本,跳过")
            continue
        best_f1, best_threshold = 0.0, float(SEMANTIC_ROUTES[intent]["threshold"])
        for threshold in CANDIDATE_THRESHOLDS:
            tp = sum(1 for s, label in samples if label and s >= threshold)
            fp = sum(1 for s, label in samples if not label and s >= threshold)
            fn = len(pos) - tp
            f1 = (2 * tp / (2 * tp + fp + fn)) if (2 * tp + fp + fn) else 0.0
            if f1 >= best_f1:
                best_f1, best_threshold = f1, threshold
        current = float(SEMANTIC_ROUTES[intent]["threshold"])
        marker = "" if abs(current - best_threshold) < 1e-9 else f"  ← 当前 {current},建议更新"
        print(f"  {intent}: 阈值 {best_threshold} (F1={best_f1:.3f}, 正样本 {len(pos)}, 负样本 {len(neg)}){marker}")
        if args.show_distribution and pos:
            neg_top = f"{max(neg):.3f}" if neg else "0"
            print(f"      正样本得分 {min(pos):.3f}~{max(pos):.3f};负样本最高 {neg_top}")

    print("\n粘贴回 semantic_routes.py 的 threshold 字段即可;改完跑回归确认。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
