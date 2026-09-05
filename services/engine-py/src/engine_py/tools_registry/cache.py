"""工具多级缓存 — 镜像 tools/src/cache.ts 的 toolCache(Redis 主路径 + 本地 Map 降级)。"""

from __future__ import annotations

import json
import time
from typing import Any


class ToolCache:
    """Redis 可用走分布式 TTL 缓存;不可用无缝降级本地内存(与 TS 行为一致)。"""

    def __init__(self) -> None:
        self._local: dict[str, tuple[str, float]] = {}

    async def get(self, key: str) -> Any | None:
        expired_at = self._local.get(key, (None, 0))[1]
        if expired_at and time.time() > expired_at:
            self._local.pop(key, None)

        try:
            from ..event_bus import get_client

            client = await get_client()
            raw = await client.get(f"toolcache:{key}")
            if raw:
                return json.loads(raw)
        except Exception:
            pass

        entry = self._local.get(key)
        return json.loads(entry[0]) if entry else None

    async def set(self, key: str, value: Any, ttl_seconds: int = 60) -> None:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        self._local[key] = (serialized, time.time() + ttl_seconds)
        try:
            from ..event_bus import get_client

            client = await get_client()
            await client.set(f"toolcache:{key}", serialized, ex=ttl_seconds)
        except Exception:
            pass

    async def delete(self, key: str) -> None:
        self._local.pop(key, None)
        try:
            from ..event_bus import get_client

            client = await get_client()
            await client.delete(f"toolcache:{key}")
        except Exception:
            pass


tool_cache = ToolCache()
