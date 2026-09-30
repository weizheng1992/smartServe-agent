"""环境配置 — 默认值与 TS 侧各模块保持一致。

对齐来源:
- packages/tools/src/cache.ts(REDIS_URL 默认)
- packages/engine/src/llm/callLLMWithRetry.ts(LLM 代理与模型名)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str) -> str:
    value = os.environ.get(key)
    return value if value else default


class ConfigError(RuntimeError):
    """必需配置缺失/非法 —— 拒绝以死端口或垃圾缺省静默启动(persona-hardening 09)。"""


def ensure_llm_config(cfg: Settings | None = None) -> None:
    """LLM 必需配置校验(persona-hardening 09,2026-09-30)。

    缺省即拒启的项:AI_BASE_URL / AI_MODEL —— 二者曾有死端口/异厂模型缺省
    (127.0.0.1:11211 与 gemini-3.5-flash,均为 TS 时代遗留),漏带 --env-file
    手拉网关时静默回退,症状像管线 bug 实为 env 没进进程(2026-09 实弹前科,
    见 memory「手拉网关必须带 --env-file」)。

    挂点为 LLM 首用(get_chat_model/get_vision_model 及 embedding 的 openai
    分支)+ gateway lifespan / worker 入口 —— 而非 Settings() 构造期:alembic
    (db:push)与 db:seed 等不涉 LLM 的脚本 import 本模块时不得被牵连拒启。

    宽于拒启的项:AI_API_KEY 缺省 "dummy" 仅显式告警(本地 mock 端点合法;
    真实端点会 401,失败点近因可辨)。DATABASE_URL / REDIS_URL 维持本地开发
    缺省不动 —— 连接拒绝即时且响亮,无静默错配面。
    """
    cfg = cfg if cfg is not None else settings
    missing = [
        name
        for name, value in (("AI_BASE_URL", cfg.llm_base_url), ("AI_MODEL", cfg.llm_model))
        if not value
    ]
    if missing:
        raise ConfigError(
            f"必需环境变量 {' / '.join(missing)} 未设置,拒绝以垃圾缺省静默启动"
            "(前科:缺省曾回退 127.0.0.1:11211 死端口,症状像管线 bug 实为 env 没进进程)。"
            "手拉服务请带 --env-file 指向仓库根 .env,或显式 export 这些变量;"
            "评测 provider 由 bun 自动加载根 .env。"
        )
    if cfg.llm_api_key == "dummy":
        print("[config] ⚠️ AI_API_KEY 仍为缺省 'dummy' —— 真实端点将 401;本地 mock 端点可忽略")


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

    # 环境变量名与 .env.example / turbo.json globalEnv 对齐为 AI_* 前缀。
    # base_url/model 刻意无缺省(空串)——垃圾缺省(TS 时代的死端口 11211 与
    # gemini 模型名)曾令漏带 --env-file 的进程静默错配;校验见 ensure_llm_config
    # (LLM 首用 + gateway lifespan / worker 入口拒启),import 本模块不受牵连。
    llm_base_url: str = field(default_factory=lambda: _env("AI_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: _env("AI_API_KEY", "dummy"))
    llm_model: str = field(default_factory=lambda: _env("AI_MODEL", ""))
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

    # L4 查询同义词改写(2026-09-12):词元+语义双空时,LLM 以货架品类词表为
    # 锚把口语措辞改写成货架检索词元重试一次(用户症状:「卖的好的背心」诚实
    # 空 —— 词元不命中、余弦 0.51-0.53 卡 0.55 阈值下,双空即终局,无第三档)。
    # 默认开;超时/异常降级空表,检索链终点仍是诚实空;改写档不叠加嵌入。
    mall_query_rewrite_enabled: bool = field(default_factory=lambda: _env("AI_MALL_QUERY_REWRITE_ENABLED", "1") == "1")
    mall_query_rewrite_timeout_seconds: float = field(
        default_factory=lambda: float(_env("AI_MALL_QUERY_REWRITE_TIMEOUT_SECONDS", "2.0"))
    )

    # 人工接管掉线释放超时(live-desk-rework P1,spec §2.1):坐席掉线后其名下
    # 接管会话在此时限内未重连即由 scheduler 幂等扫描自动释放回 AI(60~120s 档;
    # 权威路径 = DB deadline + 扫描,进程内计时器仅 UX 提示)
    takeover_release_timeout_seconds: float = field(
        default_factory=lambda: float(_env("AI_TAKEOVER_RELEASE_TIMEOUT_SECONDS", "90"))
    )

    # 排队超时回落 AI(live-desk-rework P2,spec §2.3):呼叫人工后无人认领超此
    # 限时即回 active + system 告知,与掉线释放共用 scheduler 扫描回路
    queue_fallback_timeout_seconds: float = field(
        default_factory=lambda: float(_env("AI_QUEUE_FALLBACK_TIMEOUT_SECONDS", "300"))
    )


settings = Settings()
