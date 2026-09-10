"""新用户引导话术配置(new-user-onboarding)— 单一来源解析与校验。

三段结构(wayfinder 绘图期锁定,文案依据票 01 业界调研):
- ``welcomeText`` 首访欢迎:三段式开场(身份 → 3 个能力主题 → 单一召唤);
- ``returningGreeting`` 回访新线程:一行轻问候,跳过引导;
- ``quickReplies`` 能力入口卡:3-5 个动词开头按钮,转人工固定末位。

消费方:
1. 网关 POST /api/chat/threads —— 建线程时落 welcome/greeting assistant 行
   (welcomeText + quick_replies 入口卡);
2. 引擎问候旁路(run_agent 快道 × triage 规则层)—— 罐头回复同一份配置,
   杜绝两套自我介绍;
3. admin PUT /api/tenant/{id} —— ``validate_onboarding_config`` 服务端校验。

回落链:配置存在(任何合法对象,含 {} 显式重置)即权威 —— 缺失字段直接
回落平台默认(渲染 {brand});``welcome_message`` 列仅在 onboarding_config
为 NULL 的存量租户上作 welcomeText 中继(PUT 语义携带即整体覆写,故 {}
必须是真重置,不得被旧列劫持)。
任何 DB 异常回落平台默认,冷启动不炸(架构不变量:无异常冷启动)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from .db import get_session

# ---- 平台默认文案(调研口径:2-3 句、每句一事、单一召唤、按钮 3-5 个)----
PLATFORM_ONBOARDING: dict[str, Any] = {
    "welcomeText": (
        "您好！我是 {brand} 的智能客服小助手 👋\n\n"
        "我可以帮您：\n"
        "1. 查询订单物流\n"
        "2. 办理退款售后\n"
        "3. 咨询商品信息\n\n"
        "点击下方快捷入口，或直接输入您的问题～"
    ),
    "returningGreeting": "欢迎回来！我是 {brand} 智能客服，请问这次需要帮您什么？",
    "quickRepliesTitle": "您可以直接选择：",
    "quickReplies": [
        {"label": "📦 查询订单物流", "action": "send_message", "payload": {"text": "帮我查一下最新的订单物流进度"}},
        {"label": "💰 申请退款售后", "action": "send_message", "payload": {"text": "我想申请退款"}},
        {"label": "🛍️ 咨询商品信息", "action": "send_message", "payload": {"text": "我想咨询商品信息"}},
        {"label": "🎧 转人工客服", "action": "send_message", "payload": {"text": "转人工"}},
    ],
}

_ALLOWED_KEYS = {"welcomeText", "returningGreeting", "quickRepliesTitle", "quickReplies"}
_ALLOWED_ACTIONS = {"send_message", "trigger_upload"}

_WELCOME_TEXT_MAX = 500
_RETURNING_MAX = 200
_TITLE_MAX = 50
_QUICK_REPLIES_MIN = 1
_QUICK_REPLIES_MAX = 8
_LABEL_MAX = 30
_PAYLOAD_TEXT_MAX = 100


def validate_onboarding_config(raw: Any) -> list[str]:
    """服务端 schema 校验(admin JSON 文本域入口),返回错误清单(空 = 合法)。

    严格口径:未知顶层键直接报错——JSON 手编场景下键名笔误必须显性失败,
    不得静默丢弃。
    """
    errors: list[str] = []
    if raw is None:
        return errors  # 未携带 = 不改该字段
    if not isinstance(raw, dict):
        return ["onboardingConfig 必须是 JSON 对象"]

    unknown = sorted(set(raw) - _ALLOWED_KEYS)
    if unknown:
        errors.append(f"onboardingConfig 含未知字段: {', '.join(unknown)}(允许: {', '.join(sorted(_ALLOWED_KEYS))})")

    welcome = raw.get("welcomeText")
    if welcome is not None and (not isinstance(welcome, str) or not (1 <= len(welcome.strip()) <= _WELCOME_TEXT_MAX)):
        errors.append(f"welcomeText 必须是 1-{_WELCOME_TEXT_MAX} 字的非空字符串")

    returning = raw.get("returningGreeting")
    if returning is not None and (not isinstance(returning, str) or not (1 <= len(returning.strip()) <= _RETURNING_MAX)):
        errors.append(f"returningGreeting 必须是 1-{_RETURNING_MAX} 字的非空字符串")

    title = raw.get("quickRepliesTitle")
    if title is not None and (not isinstance(title, str) or not (1 <= len(title.strip()) <= _TITLE_MAX)):
        errors.append(f"quickRepliesTitle 必须是 1-{_TITLE_MAX} 字的非空字符串")

    replies = raw.get("quickReplies")
    if replies is not None:
        if not isinstance(replies, list) or not (_QUICK_REPLIES_MIN <= len(replies) <= _QUICK_REPLIES_MAX):
            errors.append(f"quickReplies 必须是 {_QUICK_REPLIES_MIN}-{_QUICK_REPLIES_MAX} 个按钮的数组")
        else:
            for idx, item in enumerate(replies, start=1):
                prefix = f"quickReplies[{idx}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix} 必须是对象")
                    continue
                label = item.get("label")
                if not isinstance(label, str) or not (1 <= len(label.strip()) <= _LABEL_MAX):
                    errors.append(f"{prefix}.label 必须是 1-{_LABEL_MAX} 字的非空字符串")
                action = item.get("action")
                if action not in _ALLOWED_ACTIONS:
                    errors.append(f"{prefix}.action 必须是 {'/'.join(sorted(_ALLOWED_ACTIONS))} 之一")
                payload = item.get("payload")
                if not isinstance(payload, dict):
                    errors.append(f"{prefix}.payload 必须是对象")
                    continue
                if action == "send_message":
                    ptext = payload.get("text")
                    if not isinstance(ptext, str) or not (1 <= len(ptext.strip()) <= _PAYLOAD_TEXT_MAX):
                        errors.append(f"{prefix}.payload.text(action=send_message)必须是 1-{_PAYLOAD_TEXT_MAX} 字的非空字符串")
                elif action == "trigger_upload":
                    prompt = payload.get("prompt")
                    if not isinstance(prompt, str) or not (1 <= len(prompt.strip()) <= _PAYLOAD_TEXT_MAX):
                        errors.append(f"{prefix}.payload.prompt(action=trigger_upload)必须是 1-{_PAYLOAD_TEXT_MAX} 字的非空字符串")
    return errors


def _render(text: str, brand: str) -> str:
    return text.replace("{brand}", brand)


def _default_brand(business_id: str) -> str:
    clean = business_id.lower().strip()
    return f"{clean[:1].upper()}{clean[1:]} 官方旗舰店"


async def resolve_onboarding_config(business_id: str = "ecommerce") -> dict[str, Any]:
    """解析租户引导配置,任何异常回落平台默认。

    配置存在即权威:缺啥字段回落啥字段的平台默认;``{}`` = 全字段重置
    为平台默认。``welcome_message`` 列只服务 onboarding_config 为 NULL
    的存量租户(且仅中继 welcomeText,该列纯文本已含品牌词)。

    返回形状:{businessId, brandName, welcomeText, returningGreeting,
    quickRepliesTitle, quickReplies} —— 文案均为 {brand} 已渲染终稿,
    消费方(网关落库 / 引擎罐头回复)直接可用,无需再处理占位符。
    """
    clean_id = (business_id or "ecommerce").lower().strip()
    brand = _default_brand(clean_id)
    raw_config: Any = None
    welcome_message: str | None = None

    try:
        async with get_session() as session:
            name_row = (
                await session.execute(
                    text("SELECT name FROM tenants WHERE LOWER(business_id) = :bid LIMIT 1").bindparams(bid=clean_id)
                )
            ).scalar_one_or_none()
            if name_row:
                brand = name_row

            cfg_row = (
                await session.execute(
                    text(
                        "SELECT onboarding_config, welcome_message FROM tenant_configs "
                        "WHERE LOWER(business_id) = :bid ORDER BY version DESC LIMIT 1"
                    ).bindparams(bid=clean_id)
                )
            ).mappings().first()
            if cfg_row:
                raw_config = cfg_row["onboarding_config"] if isinstance(cfg_row["onboarding_config"], dict) else None
                welcome_message = cfg_row["welcome_message"] if isinstance(cfg_row["welcome_message"], str) else None
    except Exception as err:
        print(f"[Onboarding] Failed to load tenant onboarding config for {clean_id}: {err}")

    has_config = isinstance(raw_config, dict)
    config = raw_config if has_config else {}

    def _field(key: str, fallback: str) -> str:
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return _render(value, brand)
        return _render(fallback, brand)

    # welcomeText 回落链:配置存在即权威(含 {} 重置)➔ welcome_message 列
    # (仅 onboarding_config 为 NULL 的存量租户)➔ 平台默认
    raw_welcome = config.get("welcomeText")
    if isinstance(raw_welcome, str) and raw_welcome.strip():
        welcome_text = _render(raw_welcome, brand)
    elif not has_config and welcome_message and welcome_message.strip():
        welcome_text = welcome_message  # 既有列已含品牌词,不做占位符替换
    else:
        welcome_text = _render(PLATFORM_ONBOARDING["welcomeText"], brand)

    raw_replies = config.get("quickReplies")
    quick_replies = (
        [dict(item) for item in raw_replies if isinstance(item, dict)]
        if isinstance(raw_replies, list) and raw_replies
        else [dict(item) for item in PLATFORM_ONBOARDING["quickReplies"]]
    )

    return {
        "businessId": clean_id,
        "brandName": brand,
        "welcomeText": welcome_text,
        "returningGreeting": _field("returningGreeting", PLATFORM_ONBOARDING["returningGreeting"]),
        "quickRepliesTitle": _field("quickRepliesTitle", PLATFORM_ONBOARDING["quickRepliesTitle"]),
        "quickReplies": quick_replies,
    }


def build_entry_cards(config: dict[str, Any]) -> list[dict[str, Any]]:
    """由解析后的配置组装能力入口 quick_replies 卡(复用既有卡片链路,
    RichCardRenderer 原生渲染,actions 经 web CARD_ACTION_HANDLERS 分发)。"""
    return [
        {
            "type": "quick_replies",
            "data": {
                "title": config.get("quickRepliesTitle") or PLATFORM_ONBOARDING["quickRepliesTitle"],
                "options": config.get("quickReplies") or PLATFORM_ONBOARDING["quickReplies"],
            },
        }
    ]
