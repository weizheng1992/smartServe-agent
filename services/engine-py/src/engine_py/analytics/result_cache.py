"""分析结果语义缓存(三件补强之三)。

键 = 编译产物(SQL + 绑定参数)哈希 —— 同口径同参问法命中即秒回;
TTL 由 AI_RESULT_CACHE_TTL 秒控,默认 0(关)。通道逻辑在 kv.py。
"""

from __future__ import annotations

import hashlib
import json

from .kv import kv_get_json, kv_set_json


def build_key(compiled_sql: str, params: dict, chart_hint: str | None = None) -> str:
    # 图型指令入键:同一查询「折线」与「柱状」是不同交付,不共享缓存
    digest = hashlib.sha256(
        (compiled_sql + json.dumps(params, sort_keys=True, default=str)
         + (chart_hint or "")).encode()
    ).hexdigest()[:24]
    return f"da:res:{digest}"


async def get(key: str) -> dict | None:
    return await kv_get_json(key)


async def set(key: str, data: dict, ttl_seconds: int) -> None:  # noqa: A001 - 域内动词
    await kv_set_json(key, data, ttl_seconds)
