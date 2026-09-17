"""意图分类头缝(wayfinder 11-D1 三缝之①):锚点打分的可替换接口。

默认实现 AnchorIntentClassifier = 现状锚点余弦打分(embedding_anchor 判定层
的同款语义:每组锚向量取 max),行为零变化;训练产物(11 号票训练脚手架的
run 目录)将来以实现同接口的新 adapter 接入,工厂按 AI_INTENT_CLASSIFIER
切换,回滚 = 配置回退。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntentScoreResult:
    """锚点三组分数(契约冻结:未来 adapter 必须产出同形结果)。"""

    order_status: float
    refund: float
    out_of_scope: float


class AnchorIntentClassifier:
    """默认实现:对每组锚向量取与用户向量的最大余弦(现状语义逐位保持)。"""

    def score(self, *, user_vector: list[float], anchor_vectors: dict[str, list[list[float]]]) -> IntentScoreResult:
        from .semantic_cache import cosine_similarity

        def group_max(texts: list[list[float]]) -> float:
            if not texts:
                return 0.0
            return max(cosine_similarity(user_vector, v) for v in texts)

        return IntentScoreResult(
            order_status=group_max(anchor_vectors.get("order_status") or []),
            refund=group_max(anchor_vectors.get("refund") or []),
            out_of_scope=group_max(anchor_vectors.get("out_of_scope") or []),
        )
