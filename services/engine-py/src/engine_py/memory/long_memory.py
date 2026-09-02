"""长期偏好记忆 — 镜像 memory/longMemory.ts(双层画像隔离 + 专职画像 Agent)。"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re

from sqlalchemy import text

from ..db import LongMemoryFact, get_session
from ..llm import get_chat_model, get_embedding_model

PHYSIOLOGICAL_RE = re.compile(
    r"脚长|过敏|身高|体重|尺码|270mm|265mm|42码|43码|allergy|foot|size", re.IGNORECASE
)
_LINE_SPLIT_RE = re.compile(r"[\s,，、。!！?？\-_]+")


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


def _query_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for seg in _LINE_SPLIT_RE.split(query.lower()):
        if not seg:
            continue
        if re.search(r"[a-z0-9]", seg) or len(seg) <= 2:
            tokens.append(seg)
        else:
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return tokens


class LongMemory:
    def __init__(self, user_id: str, business_id: str | None = None) -> None:
        self.user_id = user_id
        self.business_id = business_id

    async def extract_and_store_fact(
        self,
        conversation_text: str,
        user_query: str | None = None,
        explicit_scope: str | None = None,
        explicit_business_id: str | None = None,
    ) -> None:
        if not self.user_id:
            print("[LongMemory] Cannot extract or store facts without userId")
            return

        # 🛡️ 专职画像 Agent 后台异步审计,不阻塞主链路
        if user_query:
            import asyncio

            asyncio.create_task(
                self._run_profile_audit(user_query, conversation_text, explicit_scope, explicit_business_id)
            )

        # 轻量正则匹配双重容灾
        for line in conversation_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            lower = line.lower()
            if "user prefers" in lower or "prefers" in lower or "fact:" in lower:
                fact_text = re.sub(r"^(fact:)", "", line, flags=re.IGNORECASE).strip()
                embedding = await get_embedding_model().aembed_query(fact_text)
                is_physiological = bool(PHYSIOLOGICAL_RE.search(fact_text))
                if explicit_scope:
                    calculated_scope = explicit_scope
                elif is_physiological:
                    calculated_scope = "global"
                elif self.business_id and self.business_id != "ecommerce":
                    calculated_scope = "tenant"
                else:
                    calculated_scope = "global"
                calculated_biz_id = (
                    explicit_business_id or self.business_id or "ecommerce"
                    if calculated_scope == "tenant"
                    else None
                )
                try:
                    async with get_session() as session:
                        session.add(
                            LongMemoryFact(
                                user_id=self.user_id,
                                business_id=calculated_biz_id,
                                scope=calculated_scope,
                                fact=fact_text,
                                embedding=json.dumps(embedding),
                                type="preference",
                                confidence=1.0,
                                status="approved",
                                source="regex_fallback",
                            )
                        )
                        await session.commit()
                except Exception:  # noqa: BLE001
                    print("[LongMemory] Insertion bypassed due to offline/failed DB.")

    async def _run_profile_audit(
        self,
        user_query: str,
        assistant_response: str,
        explicit_scope: str | None = None,
        explicit_business_id: str | None = None,
    ) -> None:
        past_orders: list[dict] = []
        try:
            async with get_session() as session:
                if self.business_id and self.business_id != "ecommerce":
                    sql = text(
                        'SELECT o.order_id AS "orderId", o.status, p.name AS "productName", '
                        "o.total_amount AS \"totalAmount\" FROM orders o "
                        "LEFT JOIN order_items oi ON o.order_id = oi.order_id "
                        "LEFT JOIN products p ON oi.product_id = p.id "
                        "WHERE o.user_id = :uid AND o.business_id = :bid LIMIT 5"
                    ).bindparams(uid=self.user_id, bid=self.business_id)
                else:
                    sql = text(
                        'SELECT o.order_id AS "orderId", o.status, p.name AS "productName", '
                        'o.total_amount AS "totalAmount" FROM orders o '
                        "LEFT JOIN order_items oi ON o.order_id = oi.order_id "
                        "LEFT JOIN products p ON oi.product_id = p.id "
                        "WHERE o.user_id = :uid LIMIT 5"
                    ).bindparams(uid=self.user_id)
                result = await session.execute(sql)
                past_orders = [dict(row) for row in result.mappings()]
        except Exception as sql_err:  # noqa: BLE001
            print(f"[Profiler Agent] Failed to fetch SQL transaction stream for audit: {sql_err}")

        system_prompt = """
你是一位世界级的消费者行为学家与多租户用户画像专家。你的职责是通过分析【用户最新的对话细节】与【历史购买流水】，提炼出符合该用户特征的个性化消费画像标签，严格判定画像的生效作用域 (scope: 'global' | 'tenant')，并进行置信度（Confidence）评估。

[CRITICAL DUAL-TIER SCOPE RULES]:
1. 'global'（全局生理/客观事实）：
   - 用户客观生理特征，例如：脚长(如 270mm/265mm)、身高、体重、衣服标准尺码(如 XL/L)、布料过敏原(如 羊毛过敏、聚酯纤维过敏)、常用快递偏好(如 优先顺丰)。
   - 这类事实跨所有商户通用，不涉及具体商户私域利益。
2. 'tenant'（特定商户私域偏好）：
   - 特定品牌/商户专属的偏好或历史，例如：耐克 Flyknit/Air Jordan 偏好、阿迪达斯椰子鞋偏好、商户专享优惠券使用习惯、特定店铺客服互动偏好。
   - 这类事实严格归属于当前商户，严禁泄漏给其它竞品商户。

[CRITICAL INSTRUCTIONS]:
请不要生成任何解释性废话。你必须只输出一个合规的 JSON 对象，包含以下字段：
{
  "hasNewPreference": boolean,
  "extractedFacts": [
    {
      "fact": string,
      "scope": "global" | "tenant",
      "confidence": number,
      "source": string
    }
  ]
}
"""
        audit_prompt = (
            f"{system_prompt}\n\n[INPUT CONTEXT]:\n"
            f"1. 🛍️ 用户历史购买流水 (SQL Transaction Stream):\n"
            f"{json.dumps(past_orders, ensure_ascii=False, indent=2, default=str)}\n\n"
            f'2. 💬 本轮最新聊天交互 (Conversational Context):\n- Customer: "{user_query}"\n'
            f'- Assistant: "{assistant_response}"\n\n请进行画像分析并返回结果 JSON：\n'
        )

        try:
            response = await get_chat_model().ainvoke(audit_prompt)
            content = response.content if hasattr(response, "content") else str(response)
            clean_json = re.sub(r"^```json\s*", "", content.strip())
            clean_json = re.sub(r"```$", "", clean_json).strip()
            audit_result = json.loads(clean_json)

            if not audit_result.get("hasNewPreference") or not audit_result.get("extractedFacts"):
                print("[Profiler Agent] 🍃 画像审计完成：本轮会话未检测到新的偏好特征变动。")
                return

            for item in audit_result["extractedFacts"]:
                try:
                    fact_text = item if isinstance(item, str) else item.get("fact")
                    confidence = 1.0 if isinstance(item, str) else item.get("confidence") or 1.0
                    source = "agent_audit_legacy" if isinstance(item, str) else item.get("source") or "agent_audit"

                    # 置信度红线路由:<0.60 丢弃;>=0.85 approved;其余 pending
                    if confidence < 0.6:
                        continue
                    status = "approved" if confidence >= 0.85 else "pending"

                    is_physiological = fact_text and PHYSIOLOGICAL_RE.search(fact_text)
                    if explicit_scope:
                        item_scope = explicit_scope
                    elif isinstance(item, dict) and item.get("scope") in ("global", "tenant"):
                        item_scope = item["scope"]
                    elif is_physiological:
                        item_scope = "global"
                    elif self.business_id and self.business_id != "ecommerce":
                        item_scope = "tenant"
                    else:
                        item_scope = "global"
                    item_biz_id = (
                        explicit_business_id or self.business_id or "ecommerce"
                        if item_scope == "tenant"
                        else None
                    )

                    embedding = await get_embedding_model().aembed_query(fact_text)
                    async with get_session() as session:
                        session.add(
                            LongMemoryFact(
                                user_id=self.user_id,
                                business_id=item_biz_id,
                                scope=item_scope,
                                fact=fact_text,
                                embedding=json.dumps(embedding),
                                type="preference",
                                confidence=confidence,
                                status=status,
                                source=source,
                            )
                        )
                        await session.commit()
                except Exception as rag_err:  # noqa: BLE001
                    print(f"[Profiler Agent] Failed to vectorise and store extracted fact: {rag_err}")
        except Exception as err:  # noqa: BLE001
            print(f"[Profiler Agent Error] 画像 Agent 提取偏好发生异常: {err}")

    async def search_relevant_facts(self, query: str, precomputed_embedding: list[float] | None = None) -> list[dict]:
        if not self.user_id:
            return []

        query_embedding = precomputed_embedding
        if not query_embedding:
            query_embedding = await get_embedding_model().aembed_query(query)

        try:
            from sqlalchemy import select

            async with get_session() as session:
                rows = (
                    (
                        await session.execute(
                            select(LongMemoryFact).where(
                                LongMemoryFact.user_id == self.user_id,
                                LongMemoryFact.status == "approved",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
        except Exception as err:  # noqa: BLE001
            print(f"[LongMemory] cosine similarity search bypassed due to offline/failed DB: {err}")
            return []

        # 🛡️ 双层画像隔离:global 全放行;tenant 仅放行当前商户
        def _tenant_visible(row: LongMemoryFact) -> bool:
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

        query_tokens = _query_tokens(query)
        scored = []
        for row in visible_rows:
            embedding_array = _parse_embedding(row.embedding)
            similarity = _cosine(query_embedding, embedding_array) if embedding_array else 0

            fact_lower = (row.fact or "").lower()
            keyword_matches = sum(1 for token in query_tokens if token in fact_lower)
            keyword_score = (
                0.55 + (keyword_matches / len(query_tokens)) * 0.45
                if query_tokens and keyword_matches > 0
                else 0
            )
            effective_score = max(similarity, keyword_score)
            scored.append(
                {
                    "fact": {
                        "id": str(row.id),
                        "fact": row.fact,
                        "category": row.type or "preference",
                        "timestamp": (row.created_at or _dt.datetime.now()).isoformat(),
                        "embedding": embedding_array or None,
                        "scope": row.scope or "global",
                        "businessId": row.business_id or None,
                        "confidence": row.confidence if row.confidence is not None else 1.0,
                        "status": row.status or "approved",
                    },
                    "similarity": effective_score,
                }
            )

        scored.sort(key=lambda item: item["similarity"], reverse=True)
        threshold = 0.55
        filtered = [item for item in scored if item["similarity"] >= threshold]
        return [item["fact"] for item in filtered[:5]]
