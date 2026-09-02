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


def _database_url() -> str:
    """DATABASE_URL 归一:TS 遗留的 postgres:// 方言串转 SQLAlchemy 可用的 postgresql+asyncpg。

    显式带驱动的 URL(postgresql+psycopg2:// 等)原样保留,便于测试容器换驱动。
    """
    url = _env("DATABASE_URL", "postgres://agent_user:agent_password@localhost:5432/agent_platform")
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_database_url)
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://:redis_password@127.0.0.1:6379"))

    temporal_address: str = field(default_factory=lambda: _env("TEMPORAL_ADDRESS", "127.0.0.1:7239"))
    temporal_namespace: str = field(default_factory=lambda: _env("TEMPORAL_NAMESPACE", "default"))
    # 影子期独立队列;切流后与 TS 共用 agent-tasks
    temporal_task_queue: str = field(default_factory=lambda: _env("TEMPORAL_TASK_QUEUE", "agent-tasks-py"))

    # 环境变量名与 .env.example / turbo.json globalEnv 对齐为 AI_* 前缀
    llm_base_url: str = field(default_factory=lambda: _env("AI_BASE_URL", "http://127.0.0.1:11211/api/openai/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("AI_API_KEY", "dummy"))
    llm_model: str = field(default_factory=lambda: _env("AI_MODEL", "gemini-3.5-flash:latest"))
    # embedding 提供方:local = 进程内免费本地推理(默认,离线可用);openai = 走 AI_BASE_URL 的 /embeddings(需付费资源包)
    embedding_provider: str = field(default_factory=lambda: _env("AI_EMBEDDING_PROVIDER", "local"))
    embedding_model: str = field(default_factory=lambda: _env("AI_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"))


settings = Settings()
