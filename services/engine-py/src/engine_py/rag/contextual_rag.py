"""Contextual RAG — 镜像 rag/contextualRag.ts(BM25 + 向量 + RRF 混合检索,物理租户隔离)。"""

from __future__ import annotations

import json
import math
import re

from sqlalchemy import select, text

from ..db import RagDocumentRow, get_session
from ..llm import get_embedding_model
from .knowledge_files import load_knowledge_chunks

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
    except Exception:
        return None


class ContextualRAG:
    def __init__(self, business_id: str | None) -> None:
        # None/''/'all' = 跨租户全局检索(SaaS 管理台上帝视角);其余值强制单租户隔离。
        # 此前网关把 all 硬编码成 ecommerce,上帝视角永远检不到他租知识(2026-09-13 修复)。
        normalized = (business_id or "").strip().lower()
        self.business_id = normalized if normalized and normalized != "all" else None

    async def _ensure_seed_data(self) -> None:
        """知识自愈播种:与 db.seed 同源读 docs/knowledge/*.md(知识不写死,
        单一来源);文件不可用/目录空则跳过播种 —— 不回退内联写死内容,否则冷启动
        降级路径会与种子漂移成两套知识(2026-09-09 评审修复)。

        2026-09-13 升级为 source 级补齐:原先只在「表全空」时播种,新增知识
        文件对已播种库永远不生效(商品知识文档因此不可见)。现按
        (business_id, source_url) 键比对,缺失的文件单独补灌 —— 幂等,已有
        文件零嵌入开销。"""
        try:
            async with get_session() as session:
                try:
                    chunks = load_knowledge_chunks()
                except Exception as files_err:
                    print(f"[RAG] Knowledge files unreadable, skip self-healing seed: {files_err}")
                    return
                if not chunks:
                    print("[RAG] docs/knowledge 无可摄取切片,跳过自愈播种(不回退内联写死内容)")
                    return
                # 文件级内容哈希比对(2026-09-13):新文件补灌,内容变更的
                # 文件整组重灌 —— 知识文档修订后无需手动清库
                existing_rows = (
                    await session.execute(
                        text(
                            "SELECT business_id, source_url, COUNT(*) AS n, "
                            "MD5(string_agg(chunk_text, '|' ORDER BY chunk_text)) AS sha "
                            "FROM rag_documents GROUP BY business_id, source_url"
                        )
                    )
                ).mappings().all()
                existing = {
                    (r["business_id"], r["source_url"]): (int(r["n"]), r["sha"])
                    for r in existing_rows
                }

                def _file_sha(file_chunks: list) -> tuple[int, str]:
                    import hashlib

                    joined = "|".join(sorted(c.chunk_text for c in file_chunks))
                    return len(file_chunks), hashlib.md5(joined.encode()).hexdigest()

                stale_keys: set[tuple[str, str]] = set()
                by_file: dict[tuple[str, str], list] = {}
                for c in chunks:
                    by_file.setdefault((c.business_id, c.source_url), []).append(c)
                for key, file_chunks in by_file.items():
                    want_n, want_sha = _file_sha(file_chunks)
                    have = existing.get(key)
                    if have is None or have[0] != want_n or have[1] != want_sha:
                        stale_keys.add(key)
                if not stale_keys:
                    return
                pending = [c for c in chunks if (c.business_id, c.source_url) in stale_keys]
                for key in stale_keys:
                    await session.execute(
                        text(
                            "DELETE FROM rag_documents WHERE business_id = :bid AND source_url = :src"
                        ).bindparams(bid=key[0], src=key[1])
                    )
                rows: list[RagDocumentRow] = []
                for chunk in pending:
                    embedding = await get_embedding_model().aembed_query(chunk.embedding_input())
                    rows.append(
                        RagDocumentRow(
                            business_id=chunk.business_id,
                            source_url=chunk.source_url,
                            chunk_text=chunk.chunk_text,
                            contextual_summary=chunk.contextual_summary(),
                            embedding=json.dumps(embedding),
                            metadata_=chunk.metadata_dict(),
                        )
                    )
                if rows:
                    session.add_all(rows)
                    await session.commit()
                    print(f"[RAG] Self-healing seed appended {len(rows)} chunks from {len({(c.business_id, c.source_url) for c in pending})} new knowledge source(s)")
        except Exception as err:
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
            except Exception as err:
                print(f"[RAG] Failed to generate embedding for search query: {err}")
                return []

        try:
            async with get_session() as session:
                stmt = select(RagDocumentRow)
                if self.business_id:
                    stmt = stmt.where(RagDocumentRow.business_id == self.business_id)
                rows = (await session.execute(stmt)).scalars().all()
        except Exception as db_err:
            # 库失败诚实空(2026-09-12):旧「Local Fake RAG」演示切片兜底退役,
            # 假相似度(0.35/0.65/0.55 关键词拍数)一并拆除 —— RAG 检索终点只有
            # 真实结果或空,与嵌入失败降级同标准(real-data-only/01)。
            print(f"[RAG] PostgreSQL query failed, returning honest empty: {db_err}")
            return []

        doc_embeddings: dict[str, float] = {}
        docs_with_tokens: list[dict] = []
        row_meta_map: dict[str, dict] = {}

        for row in rows:
            # 🔒 多租户双锁校验:应用层二次强制租户边界(全局视角 business_id=None 时放行)
            if self.business_id and row.business_id != self.business_id:
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
