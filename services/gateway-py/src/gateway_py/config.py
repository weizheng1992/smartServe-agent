"""网关配置 — DB/Redis 复用 engine_py 的 env 语义,另加网关端口。"""

from __future__ import annotations

import os

from engine_py.config import settings as engine_settings


class GatewaySettings:
    port = int(os.environ.get("PORT", "4000"))
    # DB / Redis / LLM / Temporal 全部复用 engine_py.config(单一 env 语义)
    database_url = engine_settings.database_url
    redis_url = engine_settings.redis_url


settings = GatewaySettings()
