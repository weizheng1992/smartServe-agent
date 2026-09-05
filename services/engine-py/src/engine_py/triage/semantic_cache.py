"""语义向量缓存 — 镜像 triage/semanticCache.ts(+ triage.node.ts 导出的缓存回填)。"""

from __future__ import annotations

import math
import re

from ..llm import get_embedding_model

DEFAULT_ANCHOR_PHRASES: dict[str, list[str]] = {
    "order_status": [
        "帮我查询订单物流状态",
        "看看我的订单发货了吗",
        "查询我的快递进度",
        "ORD-98712 的物流信息",
        "这个快递到哪里了",
        "查运单号进度",
        "想看一下我的订单状态",
        "哪些订单可以退货",
        "我可以退货的订单有哪些",
        "查一下支持退款的订单列表",
        "查询我名下的订单",
        "我买了什么东西",
        "查看近期的购物单据",
    ],
    "refund": [
        "我想申请退款",
        "帮货品退货退款",
        "不想要了我要退款",
        "退回我的钱",
        "退货流程怎么走",
        "怎么退款",
        "我要退货",
        "帮我把这个订单退了",
    ],
    "out_of_scope": [
        "今天天气怎么样",
        "写一段Python代码",
        "帮我订一张电影票",
        "明天会下雨吗",
        "买个东西怎么买",
        "教我做菜",
        "美国总统是谁",
        "附近好吃的餐馆有哪些",
    ],
}


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        return 0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    denom = norm_a * norm_b
    return dot / denom if denom else 0


class SemanticVectorCache:
    _tenant_cache: dict[str, list[dict]] = {}
    _embedding_cache: dict[str, list[float]] = {}
    _anchor_vectors: dict[str, list[list[float]]] | None = None
    MAX_TENANT_CACHE_SIZE = 100
    MAX_EMBEDDING_CACHE_SIZE = 500

    @classmethod
    def add_query(cls, business_id: str, query: str, reply: str, vector: list[float]) -> None:
        clean_id = (business_id or "ecommerce").lower()
        cache_list = cls._tenant_cache.get(clean_id, [])
        if any(q["query"].strip().lower() == query.strip().lower() for q in cache_list):
            return
        cache_list.append({"query": query, "reply": reply, "vector": vector})
        if len(cache_list) > cls.MAX_TENANT_CACHE_SIZE:
            cache_list = cache_list[-cls.MAX_TENANT_CACHE_SIZE :]
        cls._tenant_cache[clean_id] = cache_list

    @classmethod
    def find_best_semantic_match(
        cls, business_id: str, user_vector: list[float], min_similarity: float = 0.96
    ) -> dict | None:
        clean_id = (business_id or "ecommerce").lower()
        best_match = None
        max_similarity = 0.0
        for cached in cls._tenant_cache.get(clean_id, []):
            sim = cosine_similarity(user_vector, cached["vector"])
            if sim > max_similarity:
                max_similarity = sim
                best_match = cached
        if max_similarity >= min_similarity and best_match:
            return {"match": best_match, "similarity": max_similarity}
        return None

    @classmethod
    def inject_input_embedding(cls, text: str, vector: list[float]) -> None:
        if text and vector and len(vector) > 0:
            cls._embedding_cache[text.strip().lower()] = vector

    @classmethod
    async def get_embedding_with_cache(cls, text: str) -> list[float]:
        clean_text = text.strip().lower()
        if clean_text in cls._embedding_cache:
            return cls._embedding_cache[clean_text]
        if len(cls._embedding_cache) >= cls.MAX_EMBEDDING_CACHE_SIZE:
            first_key = next(iter(cls._embedding_cache))
            cls._embedding_cache.pop(first_key, None)
        vector = await get_embedding_model().aembed_query(clean_text)
        cls._embedding_cache[clean_text] = vector
        return vector

    @classmethod
    async def get_anchor_vectors(cls) -> dict[str, list[list[float]]]:
        if cls._anchor_vectors is not None:
            return cls._anchor_vectors

        order_list = DEFAULT_ANCHOR_PHRASES["order_status"]
        refund_list = DEFAULT_ANCHOR_PHRASES["refund"]
        oos_list = DEFAULT_ANCHOR_PHRASES["out_of_scope"]
        all_texts = order_list + refund_list + oos_list

        all_vectors = await get_embedding_model().aembed_documents(all_texts)

        cls._anchor_vectors = {
            "order_status": all_vectors[: len(order_list)],
            "refund": all_vectors[len(order_list) : len(order_list) + len(refund_list)],
            "out_of_scope": all_vectors[len(order_list) + len(refund_list) :],
        }
        return cls._anchor_vectors


def add_query_to_semantic_cache(business_id: str, query: str, reply: str, vector: list[float]) -> None:
    """镜像 triage.node.ts 的导出别名(finish 节点用于 general_query 结果缓存回填)。"""
    SemanticVectorCache.add_query(business_id, query, reply, vector)


def strip_punctuation_for_greeting(user_input: str) -> str:
    """镜像 triage 主流程的 cleanInput 规整:去标点与空白后小写。"""
    return re.sub(r"[，。！？,.!?\s]", "", user_input.lower())
