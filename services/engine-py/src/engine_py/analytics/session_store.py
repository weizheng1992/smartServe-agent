"""会话记忆(T3 多轮;wayfinder dynamic-analytics Q4b/Q6)。

通道逻辑(kv.py)之上的薄封装:只存问句与意图,不存查询结果 ——
数据永远现查,口径随时间保持有效(08-D1 同源纪律)。
"""

from __future__ import annotations

from .kv import kv_get_json, kv_set_json

_TTL_SECONDS = 24 * 3600


def _key(business_id: str | None, session_id: str) -> str:
    return f"da:sess:{business_id or 'global'}:{session_id}"


async def load(business_id: str | None, session_id: str | None) -> dict | None:
    """取会话历史 {last_question, intent};无会话/过期/存储不可达 → None。"""
    if not session_id:
        return None
    return await kv_get_json(_key(business_id, session_id))


async def save(business_id: str | None, session_id: str | None, data: dict) -> None:
    if not session_id:
        return
    await kv_set_json(_key(business_id, session_id), data, _TTL_SECONDS)
