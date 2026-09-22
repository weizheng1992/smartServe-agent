"""分析结果语义缓存(2026 业界 practice;T 之外的三件补强之三)。

键 = 编译产物(SQL + 绑定参数)哈希 —— 同口径同参问法命中即秒回;
TTL 由 AI_RESULT_CACHE_TTL 秒控,默认 0(关):测试确定性优先,dev/prod
显式开启。Redis 不可达降级进程内 TTL 字典(与 session_store 同款双通道)。
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from ..config import settings

_TTL_SECONDS = 24 * 3600  # 条目生存上限;真实过期由调用方给的 ttl 决定
_MEM: dict[str, tuple[float, str]] = {}
_client: Any = None


def build_key(compiled_sql: str, params: dict) -> str:
    digest = hashlib.sha256(
        (compiled_sql + json.dumps(params, sort_keys=True, default=str)).encode()
    ).hexdigest()[:24]
    return f"da:res:{digest}"


def _get_client():
    global _client
    if _client is None:
        import redis.asyncio as aioredis

        _client = aioredis.from_url(
            settings.redis_url, socket_timeout=0.5, decode_responses=True,
        )
    return _client


async def get(key: str) -> dict | None:
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


async def set(key: str, data: dict, ttl_seconds: int) -> None:
    raw = json.dumps(data, ensure_ascii=False, default=str)
    try:
        await _get_client().set(key, raw, ex=max(int(ttl_seconds), 1))
    except Exception:
        _MEM[key] = (time.time() + ttl_seconds, raw)
