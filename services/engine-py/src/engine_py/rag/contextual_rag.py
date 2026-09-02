"""Contextual RAG — 镜像 rag/contextualRag.ts(BM25 + 向量 + RRF 混合检索,物理租户隔离)。"""

from __future__ import annotations

import json
import math
import re

from sqlalchemy import select

from ..db import RagDocumentRow, get_session
from ..llm import get_embedding_model

_TOKENIZE_RE = re.compile(r"[a-z0-9]+|[一-龥]")


def tokenize(text: str) -> list[str]:
    """混合分词器:英文/数字按词,CJK 按单字。"""
    return _TOKENIZE_RE.findall(text.lower())


def compute_bm25(query: str, docs: list[dict]) -> dict[str, float]:
    """经典 BM25(k1=1.2, b=0.75)。"""
    query_tokens = tokenize(query)
    scores: dict[str, float] = {}
    if not query_tokens or not docs:
        return {doc["id"]: 0.0 for doc in docs}

    n = len(docs)
    k1, b = 1.2, 0.75
    total_length = sum(len(doc["tokens"]) for doc in docs)
    avgdl = total_length / n or 1

    idf: dict[str, float] = {}
    for token in query_tokens:
        n_q = sum(1 for doc in docs if token in doc["tokens"])
        idf[token] = math.log(max(0.0001, (n - n_q + 0.5) / (n_q + 0.5) + 1))

    for doc in docs:
        doc_len = len(doc["tokens"])
        term_freqs: dict[str, int] = {}
        for token in doc["tokens"]:
            term_freqs[token] = term_freqs.get(token, 0) + 1

        score = 0.0
        for token in query_tokens:
            f = term_freqs.get(token, 0)
            if f > 0:
                numerator = f * (k1 + 1)
                denominator = f + k1 * (1 - b + b * (doc_len / avgdl))
                score += idf.get(token, 0) * (numerator / denominator)
        scores[doc["id"]] = score
    return scores


def reciprocal_rank_fusion(vector_rank: list[dict], bm25_rank: list[dict], k: int = 60) -> dict[str, float]:
    """倒数排名融合(RRF)。"""
    rrf_scores: dict[str, float] = {}

    def _apply(rank_list: list[dict]) -> None:
        for index, item in enumerate(rank_list):
            rank = index + 1
            rrf_scores[item["id"]] = rrf_scores.get(item["id"], 0) + 1 / (k + rank)

    _apply(vector_rank)
    _apply(bm25_rank)
    return rrf_scores


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0


def _parse_embedding(raw) -> list[float] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return value if isinstance(value, list) else None
    except Exception:  # noqa: BLE001
        return None


SEED_DOCS = [
    {
        "businessId": "ecommerce",
        "chunkText": "对于我们电商主站的订单，普通用户享有自签收之日起 7 天无理由退换货权益。退回的商品必须保持吊牌完整、未拆封且不影响二次销售。非质量问题的退货由买家自行承担寄回运费。",
        "contextualSummary": "这段切片描述了电商主站（ecommerce）标准 7 天无理由退换货的前提条件与退货运费归属政策。",
        "category": "refund_policy",
    },
    {
        "businessId": "nike",
        "chunkText": "Nike 会员专属福利：支持自订单购买之日起 30 天超长无理由退换货。即使已经拆除吊牌或进行过试穿，只要鞋底无明显磨损，均可享受免费原路退款。退款通过顺丰速运免费寄回。",
        "contextualSummary": "这段切片详细说明了 Nike 会员尊享的 30 天无损无理由退货、已拆吊牌退货政策以及顺丰寄回服务。",
        "category": "refund_policy",
    },
    {
        "businessId": "adidas",
        "chunkText": "Adidas 支持签收后 14 天退换货。所有商品必须保留原始包装盒与防伪扣，试穿时请勿弄脏鞋底。退货需要通过官方微信小程序预约快递员上门取件，不支持自行寄送。",
        "contextualSummary": "这段切片详细规定了 Adidas 的 14 天退换货时效、原始防伪包装要求，以及微信小程序预约取件的硬性物流约束。",
        "category": "refund_policy",
    },
    {
        "businessId": "nike",
        "chunkText": "Nike 官方鞋码对照与版型建议：Pegasus 飞马系列跑鞋版型紧凑、足弓包裹感极强。常规脚型建议选择比正装皮鞋大半码；高足弓或宽脚掌用户，强烈建议购买大一码（例如平时穿42码，建议选42.5码或43码），否则易出现脚趾顶红或严重的侧向挤压感。",
        "contextualSummary": "这段切片详细规定了 Nike 运动鞋（特别是飞马系列跑鞋）的鞋码对照和版型偏小的尺码升级建议。",
        "category": "size_chart",
    },
    {
        "businessId": "adidas",
        "chunkText": "Adidas 服饰尺码指南：Adidas 户外运动夹克、卫衣与连帽衫整体采用欧美版型剪裁，版型偏向宽松和落肩、Oversized 风格。如果您平时穿着 L 码（适合175cm-180cm），且偏好贴身或标准挺拔版型，建议选择比常规尺码小一号（即 M 码）。",
        "category": "size_chart",
        "contextualSummary": "这段切片详细规定了 Adidas 衣服欧版偏宽松落肩的设计特征及建议买小一码的尺码指南。",
    },
    {
        "businessId": "ecommerce",
        "chunkText": "电商主站常规服饰尺码：通用针织衫、纯棉打底衫尺码为标准中国国标码。M 码适合身高 170cm 左右，L 码适合身高 175cm 左右，XL 码适合身高 180cm 左右。因纯棉材质存在正常 1.5% 的缩水率，建议身高卡在边缘或体型微胖的用户选择大一码。",
        "category": "size_chart",
        "contextualSummary": "这段切片规定了电商主站针织衫等标准国标尺码对照，以及考虑纯棉缩水率后的微胖大一码推荐。",
    },
]


class ContextualRAG:
    def __init__(self, business_id: str) -> None:
        self.business_id = business_id

    async def _ensure_seed_data(self) -> None:
        """知识库为空时自动注入高保真演示数据(与 TS 自愈逻辑一致)。"""
        try:
            async with get_session() as session:
                existing = (
                    await session.execute(select(RagDocumentRow.id).limit(1))
                ).scalar_one_or_none()
                if existing is not None:
                    return
                for doc in SEED_DOCS:
                    combined_text = f"[Context] {doc['contextualSummary']}\n\n[Content] {doc['chunkText']}"
                    embedding = await get_embedding_model().aembed_query(combined_text)
                    session.add(
                        RagDocumentRow(
                            business_id=doc["businessId"],
                            chunk_text=doc["chunkText"],
                            contextual_summary=doc["contextualSummary"],
                            embedding=json.dumps(embedding),
                            metadata={"category": doc["category"], "version": "1.0"},
                        )
                    )
                await session.commit()
        except Exception as err:  # noqa: BLE001
            print(f"[RAG] Self-healing seed failed (possibly due to offline/mocked DB): {err}")

    async def search_relevant_docs(
        self,
        query: str,
        limit: int = 2,
        precomputed_embedding: list[float] | None = None,
        category: str | None = None,
        min_score: float = 0.4,
    ) -> list[dict]:
        await self._ensure_seed_data()

        query_embedding = precomputed_embedding
        if not query_embedding:
            try:
                query_embedding = await get_embedding_model().aembed_query(query)
            except Exception as err:  # noqa: BLE001
                print(f"[RAG] Failed to generate embedding for search query: {err}")
                return []

        try:
            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            select(RagDocumentRow).where(RagDocumentRow.business_id == self.business_id)
                        )
                    )
                    .scalars()
                    .all()
                )
        except Exception as db_err:  # noqa: BLE001
            print(f"[RAG] PostgreSQL query failed, falling back to Local Fake RAG: {db_err}")
            return self._search_local_fake_docs(query)

        doc_embeddings: dict[str, float] = {}
        docs_with_tokens: list[dict] = []
        row_meta_map: dict[str, dict] = {}

        for row in rows:
            # 🔒 多租户双锁校验:应用层二次强制租户边界
            if row.business_id != self.business_id:
                continue
            row_meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
            row_meta_map[str(row.id)] = row_meta
            if category and row_meta.get("category") and row_meta.get("category") != category:
                continue

            embedding_array = _parse_embedding(row.embedding)
            similarity = _cosine(query_embedding, embedding_array) if embedding_array else 0
            doc_embeddings[str(row.id)] = similarity
            docs_with_tokens.append(
                {
                    "id": str(row.id),
                    "tokens": tokenize(
                        f"{row_meta.get('docTitle') or ''} {row_meta.get('headerPath') or ''} "
                        f"{row.contextual_summary or ''} {row.chunk_text}"
                    ),
                }
            )

        bm25_scores = compute_bm25(query, docs_with_tokens)

        vector_rank = sorted(
            ({"id": doc_id, "score": score} for doc_id, score in doc_embeddings.items()),
            key=lambda item: item["score"],
            reverse=True,
        )
        bm25_rank = sorted(
            ({"id": doc_id, "score": score} for doc_id, score in bm25_scores.items() if score > 0),
            key=lambda item: item["score"],
            reverse=True,
        )
        rrf_scores = reciprocal_rank_fusion(vector_rank, bm25_rank, 60)

        scored_docs = []
        for row in rows:
            row_id = str(row.id)
            if row_id not in doc_embeddings:
                continue
            similarity = doc_embeddings[row_id]
            bm25_score = bm25_scores.get(row_id, 0)
            meta = row_meta_map.get(row_id, {})
            normalized_bm25 = bm25_score / (bm25_score + 1)
            hybrid_score = similarity * 0.8 + normalized_bm25 * 0.2
            if hybrid_score >= min_score:
                scored_docs.append(
                    {
                        "id": row_id,
                        "businessId": row.business_id,
                        "sourceUrl": row.source_url or None,
                        "chunkText": row.chunk_text,
                        "contextualSummary": row.contextual_summary or "",
                        "similarity": hybrid_score,
                        "category": meta.get("category"),
                        "headerPath": meta.get("headerPath"),
                        "docTitle": meta.get("docTitle"),
                        "parentChunk": meta.get("parentChunk"),
                    }
                )

        scored_docs.sort(key=lambda doc: rrf_scores.get(doc["id"], 0), reverse=True)
        return scored_docs[:limit]

    def _search_local_fake_docs(self, query: str) -> list[dict]:
        """离线高保真兜底(与 TS 版三条演示切片一致)。"""
        fake_data = SEED_DOCS[:3]
        fake_ids = ["fake_rag_1", "fake_rag_2", "fake_rag_3"]
        filtered = []
        for doc, fake_id in zip(fake_data, fake_ids):
            if doc["businessId"] != self.business_id:
                continue
            filtered.append({"id": fake_id, **doc})

        docs_with_tokens = [
            {"id": d["id"], "tokens": tokenize(f"{d.get('contextualSummary') or ''} {d['chunkText']}")}
            for d in filtered
        ]
        bm25_scores = compute_bm25(query, docs_with_tokens)

        query_lower = query.lower()
        results = []
        for d in filtered:
            bm25_score = bm25_scores.get(d["id"], 0)
            normalized_bm25 = bm25_score / (bm25_score + 1)
            simulated_vector_similarity = 0.35
            if self.business_id.lower() in query_lower:
                simulated_vector_similarity = 0.65
            elif any(kw in query_lower for kw in ("退", "refund", "return", "换货")):
                simulated_vector_similarity = 0.55
            hybrid_score = simulated_vector_similarity * 0.8 + normalized_bm25 * 0.2
            results.append({**d, "similarity": hybrid_score})

        results = [r for r in results if r["similarity"] >= 0.4]
        results.sort(key=lambda r: r["similarity"], reverse=True)
        return results[:2]
