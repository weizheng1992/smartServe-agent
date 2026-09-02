"""环境配置 — 默认值与 TS 侧各模块保持一致。

对齐来源:
- packages/tools/src/cache.ts(REDIS_URL 默认)
- packages/engine/src/temporal/client.ts(TEMPORAL_ADDRESS 默认)
- packages/engine/src/llm/callLLMWithRetry.ts(LLM 代理与模型名)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str) -> str:
    value = os.environ.get(key)
    return value if value else default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgres://agent_user:agent_password@localhost:5432/agent_platform"))
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://:redis_password@127.0.0.1:6379"))

    temporal_address: str = field(default_factory=lambda: _env("TEMPORAL_ADDRESS", "127.0.0.1:7239"))
    temporal_namespace: str = field(default_factory=lambda: _env("TEMPORAL_NAMESPACE", "default"))
    # 影子期独立队列;切流后与 TS 共用 agent-tasks
    temporal_task_queue: str = field(default_factory=lambda: _env("TEMPORAL_TASK_QUEUE", "agent-tasks-py"))

    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://127.0.0.1:11211/api/openai/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", "dummy"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gemini-3.5-flash:latest"))
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "text-embedding-005:latest"))


settings = Settings()
