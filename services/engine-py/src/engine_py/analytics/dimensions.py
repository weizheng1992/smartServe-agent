"""命名实体维度解析(ADR-0005;LLM 意图层的确定性落地侧)。

LLM 只输出「实体提及」原文;落库命中由本模块确定性完成(ILIKE 前缀/包含),
多命中交回 clarify 反问,零命中响亮失败 —— 用户输入永不进 SQL 文本。
"""

from __future__ import annotations

from sqlalchemy import text

from ..tools_registry import order_domain

_ENTITY_KINDS = ("promotion", "customer", "spu")


def kind_label(kind: str) -> str:
    return {"promotion": "活动", "customer": "客户", "spu": "商品"}.get(kind, kind)


async def resolve_entity(kind: str, mention: str, limit: int = 8) -> list[dict]:
    """实体提及 → 候选列表 [{id, label}];id 即意图实体槽的绑定值。"""
    mention = (mention or "").strip()
    if not mention:
        return []
    if kind not in _ENTITY_KINDS:
        raise UnsupportedEntityKind(kind)
    async with order_domain._merchant_reader_engine().connect() as conn:
        if kind == "promotion":
            rows = (
                await conn.execute(text(
                    "SELECT id::text AS id, name AS label FROM promotions "
                    "WHERE name ILIKE :m ORDER BY created_at DESC LIMIT :lim"
                ).bindparams(m=f"%{mention}%", lim=limit))
            ).mappings().all()
        elif kind == "customer":
            rows = (
                await conn.execute(text(
                    "SELECT customer_id AS id, name || ' · ' || phone AS label FROM merchant_customers "
                    "WHERE name ILIKE :m OR phone ILIKE :m OR customer_id ILIKE :m "
                    "ORDER BY created_at DESC LIMIT :lim"
                ).bindparams(m=f"%{mention}%", lim=limit))
            ).mappings().all()
        else:  # spu
            rows = (
                await conn.execute(text(
                    "SELECT spu_code AS id, title AS label FROM merchant_spus "
                    "WHERE title ILIKE :m OR spu_code ILIKE :m ORDER BY title LIMIT :lim"
                ).bindparams(m=f"%{mention}%", lim=limit))
            ).mappings().all()
    return [dict(r) for r in rows]


async def list_candidates(kind: str, limit: int = 8) -> list[dict]:
    """未指明实体时的候选清单(clarify 反问选项;按最近/最大取前 N)。"""
    if kind not in _ENTITY_KINDS:
        raise UnsupportedEntityKind(kind)
    async with order_domain._merchant_reader_engine().connect() as conn:
        if kind == "promotion":
            rows = (
                await conn.execute(text(
                    "SELECT id::text AS id, name AS label FROM promotions "
                    "ORDER BY created_at DESC LIMIT :lim"
                ).bindparams(lim=limit))
            ).mappings().all()
        elif kind == "customer":
            rows = (
                await conn.execute(text(
                    "SELECT c.customer_id AS id, c.name || ' · ' || c.phone AS label "
                    "FROM merchant_customers c LEFT JOIN merchant_orders o ON o.customer_id = c.customer_id "
                    "GROUP BY c.customer_id, c.name, c.phone ORDER BY COUNT(o.order_id) DESC, c.created_at DESC LIMIT :lim"
                ).bindparams(lim=limit))
            ).mappings().all()
        else:  # spu
            rows = (
                await conn.execute(text(
                    "SELECT spu_code AS id, title AS label FROM merchant_spus "
                    "WHERE status = 'ON_SALE' ORDER BY title LIMIT :lim"
                ).bindparams(lim=limit))
            ).mappings().all()
    return [dict(r) for r in rows]


class UnsupportedEntityKind(Exception):
    """未知实体种类(编程错误,非用户问题)。"""


async def entity_ids_exist(kind: str, ids: list[str]) -> bool:
    """意图实体槽引用的实体是否仍存在(L2 范例回放前校验;陈旧 → 停用范例)。"""
    if not ids:
        return True
    table, col = {
        "promotion": ("promotions", "id::text"),
        "customer": ("merchant_customers", "customer_id"),
        "spu": ("merchant_spus", "spu_code"),
    }[kind]
    async with order_domain._merchant_reader_engine().connect() as conn:
        row = (
            await conn.execute(text(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {col} = ANY(:ids)"
            ).bindparams(ids=list(ids)[:20]))
        ).scalar()
    return bool(row)
