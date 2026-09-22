"""会话记忆(T3 多轮;wayfinder dynamic-analytics Q4b/Q6)。

Redis 按 session_id 存「最近一轮问句 + 结构化意图」(TTL 24h);Redis 不可达
时降级进程内 TTL 字典(单进程 dev 等价)。只存问句与意图,不存查询结果 ——
数据永远现查,口径随时间保持有效(08-D1 同源纪律)。
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..config import settings

_TTL_SECONDS = 24 * 3600
_MEM: dict[str, tuple[float, str]] = {}
_client: Any = None


def _key(business_id: str | None, session_id: str) -> str:
    return f"da:sess:{business_id or 'global'}:{session_id}"


def _get_client():
    global _client
    if _client is None:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(
            settings.redis_url, socket_timeout=0.5, decode_responses=True,
        )
    return _client


async def load(business_id: str | None, session_id: str | None) -> dict | None:
    """取会话历史 {last_question, intent};无会话/过期/存储不可达 → None。"""
    if not session_id:
        return None
    key = _key(business_id, session_id)
    raw = None
    try:
        raw = await _get_client().get(key)
    except Exception:
        item = _MEM.get(key)
        raw = item[1] if item and item[0] > time.time() else None
        if raw is None:
            _MEM.pop(key, None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def save(business_id: str | None, session_id: str | None, data: dict) -> None:
    if not session_id:
        return
    key = _key(business_id, session_id)
    raw = json.dumps(data, ensure_ascii=False, default=str)
    try:
        await _get_client().set(key, raw, ex=_TTL_SECONDS)
    except Exception:
        _MEM[key] = (time.time() + _TTL_SECONDS, raw)
