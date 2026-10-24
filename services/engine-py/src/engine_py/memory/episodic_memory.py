"""情境记忆 — 镜像 memory/episodicMemory.ts(带时间戳事件 + 双层租户隔离)。"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re

from sqlalchemy import select

from ..db import EpisodicEventRow, get_session
from ..llm import get_embedding_model
from ..tenant_context import resolve_business_id
from ..vectors import cosine_similarity, parse_embedding
from .tenant_scope import tenant_scope_condition

_TOKEN_SPLIT_RE = re.compile(r"[\s,，、。!！?？]+")


class EpisodicMemory:
    def __init__(self, user_id: str, business_id: str | None = None) -> None:
        self.user_id = user_id
        self.business_id = business_id

    async def add_event(
        self,
        event: str,
        importance_score: int,
        scope: str = "tenant",
        business_id: str | None = None,
    ) -> None:
        if not self.user_id:
            print("[EpisodicMemory] Cannot add event without userId")
            return
        target_biz_id = (
            resolve_business_id(business_id or self.business_id) if scope == "tenant" else None
        )  # A7:tenant 域归属先吃入口上下文,再落平台默认
        embedding = await get_embedding_model().aembed_query(event)
        try:
            async with get_session() as session:
                session.add(
                    EpisodicEventRow(
                        user_id=self.user_id,
                        business_id=target_biz_id,
                        scope=scope,
                        content=event,
                        embedding=json.dumps(embedding),
                        importance=importance_score,
                    )
                )
                await session.commit()
        except Exception:
            print("[EpisodicMemory] Insertion bypassed due to offline/failed DB.")

    async def retrieve_events(
        self, query: str, limit: int = 3, precomputed_embedding: list[float] | None = None
    ) -> list[dict]:
        if not self.user_id:
            return []

        query_embedding = precomputed_embedding
        if not query_embedding:
            query_embedding = await get_embedding_model().aembed_query(query)

        try:
            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            select(EpisodicEventRow)
                            .where(
                                EpisodicEventRow.user_id == self.user_id,
                                # 租户过滤下沉 SQL(2026-09-21 拷问轮决议);Python 侧保留防御
                                tenant_scope_condition(EpisodicEventRow, self.business_id),
                            )
                            .order_by(EpisodicEventRow.timestamp.desc())
                            .limit(50)
                        )
                    )
                    .scalars()
                    .all()
                )
        except Exception as err:
            print(f"[EpisodicMemory] cosine similarity search bypassed due to offline/failed DB: {err}")
            return []

        def _tenant_visible(row: EpisodicEventRow) -> bool:
            if not row.scope or row.scope == "global":
                return True
            if row.scope == "tenant":
                if self.business_id and self.business_id != "ecommerce":
                    return row.business_id == self.business_id
                return not row.business_id or row.business_id == "ecommerce" or row.business_id == self.business_id
            return False

        visible_rows = [row for row in rows if _tenant_visible(row)]
        if not visible_rows:
            return []

        query_tokens = [t for t in _TOKEN_SPLIT_RE.split(query.lower()) if len(t) >= 2]
        # 三因子打分(2026-10-24 SOTA 对齐 P0-1):相关性(base)×时近性×重要性
        # —— importance 此前落库但检索完全不用(LongMemEval 弱项:时序推理)。
        # 乘法降级不灭失:90 天旧事件 ×0.85 档仍可凭高相关过 0.55 阈值。
        now = _dt.datetime.now()
        scored = []
        for row in visible_rows:
            embedding_array = parse_embedding(row.embedding)
            similarity = cosine_similarity(query_embedding, embedding_array) if embedding_array else 0
            content_lower = (row.content or "").lower()
            keyword_matches = sum(1 for token in query_tokens if token in content_lower)
            keyword_score = (keyword_matches / len(query_tokens)) * 0.95 if query_tokens else 0
            base = max(similarity, keyword_score)
            if row.timestamp:
                age_days = max((now - row.timestamp).days, 0)
            else:
                age_days = 0
            recency_factor = 0.85 + 0.15 * math.exp(-age_days / 30.0)
            # falsy 守卫:importance=0 是合法分值,严禁被 `or 3` 吞成 3 反而提权
            importance = row.importance if row.importance is not None else 3
            importance_factor = 0.8 + 0.2 * min(int(importance), 9) / 9.0
            effective_score = base * recency_factor * importance_factor
            scored.append(
                {
                    "event": {
                        "id": str(row.id),
                        "event": row.content,
                        "importanceScore": row.importance or 3,
                        "timestamp": (row.timestamp or "").isoformat() if row.timestamp else None,
                        "embedding": embedding_array or None,
                        "scope": row.scope or "global",
                        "businessId": row.business_id or None,
                    },
                    "similarity": effective_score,
                    "base": base,
                }
            )

        scored.sort(key=lambda item: item["similarity"], reverse=True)
        # 阈值锚定在 base(2026-10-24 code-review):recency/importance 两因子只
        # 重排不弃召回 —— 乘法后旧低权事件的 effective 被系统性压到 0.55 之下
        # 会静默改变召回边界(最劣 0.55/0.68≈0.81),与「降级不灭失」矛盾
        filtered = [item for item in scored if item["base"] >= 0.55]
        return [item["event"] for item in filtered[:limit]]
