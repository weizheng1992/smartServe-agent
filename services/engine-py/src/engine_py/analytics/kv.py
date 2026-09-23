"""Redis 优先 / 进程内 TTL 字典回落 的共享 KV 基座。

session_store 与 result_cache 的双通道逻辑曾逐行雷同(code-review 判断题),
收敛于此:取值接点(get/set)各自实现,通道选择归本模块。
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..config import settings

_MEM: dict[str, tuple[float, str]] = {}
_client: Any = None


def _get_client():
    global _client
    if _client is None:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(
            settings.redis_url, socket_timeout=0.5, decode_responses=True,
        )
    return _client


async def kv_get(key: str) -> str | None:
    """取原始字符串;Redis 不可达回落进程内 TTL;过期即清。"""
    try:
        raw = await _get_client().get(key)
    except Exception:
        item = _MEM.get(key)
        raw = item[1] if item and item[0] > time.time() else None
        if raw is None:
            _MEM.pop(key, None)
    return raw


async def kv_set(key: str, raw: str, ttl_seconds: int) -> None:
    """写原始字符串(TTL 秒);Redis 不可达回落进程内。"""
    try:
        await _get_client().set(key, raw, ex=max(int(ttl_seconds), 1))
    except Exception:
        _MEM[key] = (time.time() + ttl_seconds, raw)


async def kv_get_json(key: str) -> dict | None:
    raw = await kv_get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def kv_set_json(key: str, data: dict, ttl_seconds: int) -> None:
    await kv_set(key, json.dumps(data, ensure_ascii=False, default=str), ttl_seconds)
