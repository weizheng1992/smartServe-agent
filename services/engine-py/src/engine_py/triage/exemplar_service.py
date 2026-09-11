"""租户专属 Few-Shot 榜样召回 — 镜像 triage/exemplarService.ts(物理租户隔离)。"""

from __future__ import annotations

import asyncio
import os
import re

from sqlalchemy import select

from ..db import IntentExemplar, get_session
from ..llm import get_embedding_model
from .semantic_cache import cosine_similarity

_NGRAM_STRIP_RE = re.compile(r"[\s,，。！？!?.、:：;；_—\-/]+")

# 检索超时(工单05 2026-09-11):样本召回挂在 triage 主链上,LLM 例句服务拖慢时
# 不能陪挂 —— 超时与异常同降级空列表;对齐 AI_VISION_TIMEOUT_SECONDS 先例经 env 可调
EXEMPLAR_RETRIEVAL_TIMEOUT_SECONDS = float(os.getenv("AI_EXEMPLAR_TIMEOUT_SECONDS", "0.2"))


def _calculate_text_overlap(query: str, text: str) -> float:
    q = query.strip().lower()
    t = text.strip().lower()
    if not q or not t:
        return 0
    if q in t or t in q:
        return 0.8

    def _ngrams(s: str, n: int = 2) -> set[str]:
        clean = _NGRAM_STRIP_RE.sub("", s)
        return {clean[i : i + n] for i in range(len(clean) - n + 1)}

    ngrams_a = _ngrams(q)
    ngrams_b = _ngrams(t)
    if not ngrams_a or not ngrams_b:
        return 0
    intersection = len(ngrams_a & ngrams_b)
    min_size = min(len(ngrams_a), len(ngrams_b))
    return (intersection / min_size) * 0.8 if min_size else 0


async def _search_relevant_exemplars_impl(
    tenant_id: str,
    query: str,
    query_embedding: list[float] | None = None,
    limit: int = 3,
) -> list[dict]:
    clean_tenant_id = (tenant_id or "ecommerce").lower()
    async with get_session() as session:
        # 确定性排序(工单05):created_at+id 双键 —— 同租户同 limit 下取到的
        # 样本集稳定(无序取 50 会让 prompt 上下文随物理行序抖动),且偏向最新样本
        rows = (
            (
                await session.execute(
                    select(IntentExemplar)
                    .where(IntentExemplar.business_id == clean_tenant_id, IntentExemplar.is_active.is_(True))
                    .order_by(IntentExemplar.created_at.desc(), IntentExemplar.id.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return []

    target_vec = query_embedding
    if not target_vec:
        target_vec = await get_embedding_model().aembed_query(query)

    scored = []
    for row in rows:
        vec_sim = 0.0
        if row.embedding and isinstance(row.embedding, list):
            vec_sim = cosine_similarity(target_vec, row.embedding)
        text_overlap = _calculate_text_overlap(query, row.example_text)
        scored.append(
            {
                "id": str(row.id),
                "businessId": row.business_id,
                "intentName": row.intent_name,
                "exampleText": row.example_text,
                "similarity": max(vec_sim, text_overlap),
            }
        )

    scored = [item for item in scored if item["similarity"] >= 0.05]
    scored.sort(key=lambda item: item["similarity"], reverse=True)
    return scored[:limit]


async def search_relevant_exemplars(
    tenant_id: str,
    query: str,
    query_embedding: list[float] | None = None,
    limit: int = 3,
) -> list[dict]:
    clean_tenant_id = (tenant_id or "ecommerce").lower()
    try:
        return await asyncio.wait_for(
            _search_relevant_exemplars_impl(tenant_id, query, query_embedding, limit),
            timeout=EXEMPLAR_RETRIEVAL_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        print(
            f"[ExemplarService] 租户[{clean_tenant_id}] 样本检索超时"
            f"(>{EXEMPLAR_RETRIEVAL_TIMEOUT_SECONDS}s),降级空列表"
        )
        return []
    except Exception as err:
        print(f"[ExemplarService] 租户[{clean_tenant_id}] 样本检索失败,降级空列表: {err}")
        return []


def format_exemplars_for_prompt(exemplars: list[dict]) -> str:
    if not exemplars:
        return ""
    return "\n".join(
        f'Sample {idx + 1}: Query "{ex["exampleText"]}" -> Intent: "{ex["intentName"]}"'
        for idx, ex in enumerate(exemplars)
    )


async def add_exemplar(
    tenant_id: str,
    intent_name: str,
    example_text: str,
    embedding: list[float] | None = None,
) -> str:
    clean_tenant_id = (tenant_id or "ecommerce").lower()
    vec = embedding or await get_embedding_model().aembed_query(example_text)
    async with get_session() as session:
        row = IntentExemplar(
            business_id=clean_tenant_id,
            intent_name=intent_name,
            example_text=example_text,
            embedding=vec,
            is_active=True,
        )
        session.add(row)
        await session.commit()
        return str(row.id)
