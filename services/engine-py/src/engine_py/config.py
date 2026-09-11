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
    # 视觉模型(wayfinder multimodal 001/003):独立模型配置,base_url/key 复用上方;
    # GLM-4.6V 无 response_format,结构化输出须 method="function_calling"(tools 白名单)
    vision_model: str = field(default_factory=lambda: _env("AI_VISION_MODEL", "glm-4.6v"))
    vision_timeout_seconds: float = field(default_factory=lambda: float(_env("AI_VISION_TIMEOUT_SECONDS", "30")))

    # glm-4.7 每次调用默认开思维链(reasoning_content):裸测"只回复ok"也先生成 131-239
    # 推理 token,管线单次调用 11-74s(2026-09-09 实测,商户咨询类回复 57-114s 的大头)。
    # 客服管线不需要深度推理,默认关闭换 4-10 倍延迟;disabled=注入 thinking 关闭参数,
    # enabled=不注入(模型默认);换不支持 thinking 参数的提供方时置 enabled 规避 400。
    llm_thinking: str = field(default_factory=lambda: _env("AI_THINKING", "disabled"))
    # planner 深度规划输出上限:曾对「退货政策」类简单问题生成 5163 token(73.7s),
    # 封顶防失控;截断 JSON 会落 planner 兜底单步计划(功能降级不炸会话)
    planner_max_tokens: int = field(default_factory=lambda: int(_env("AI_PLANNER_MAX_TOKENS", "2000")))

    # L2 商品语义召回(2026-09-11):词元 ILIKE 查空时 bge 余弦补位。默认开;
    # 阈值 0.55 系真 bge-small-zh 实测定标(2026-09-11 实测分布:口语措辞 vs
    # 商品文案的正例落 0.56-0.58、无关品类 0.36-0.45 —— bge-small 的余弦
    # 绝对值整体偏低,0.6 会把全部正例挡掉),与 RAG 直答 0.55 同档。嵌入
    # 不可用/异常时降级诚实空,绝不阻断检索。
    mall_semantic_enabled: bool = field(default_factory=lambda: _env("AI_MALL_SEMANTIC_ENABLED", "1") == "1")
    mall_semantic_min_similarity: float = field(
        default_factory=lambda: float(_env("AI_MALL_SEMANTIC_MIN_SIMILARITY", "0.55"))
    )


settings = Settings()
