"""onboarding_config 配置底座(new-user-onboarding A)。

钉死三件事:
1. ``validate_onboarding_config`` 服务端 schema 校验(未知键显性失败、
   逐字段边界);纯函数,零 DB。
2. ``resolve_onboarding_config`` 回落语义:配置存在(含 {} 显式重置)即
   权威,缺失字段直接回落平台默认;welcome_message 列仅服务
   onboarding_config 为 NULL 的存量租户(仅中继 welcomeText);{brand}
   占位符渲染(tenants.name 优先,缺行降级 prettified business_id)。
3. DB 异常回落平台默认,冷启动不炸。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text

from engine_py.db import get_session
from engine_py.onboarding import (
    PLATFORM_ONBOARDING,
    build_entry_cards,
    resolve_onboarding_config,
    validate_onboarding_config,
)

pytestmark = pytest.mark.usefixtures("pg_factory")

_BID = "onboard-test"


def _seed_tenant(onboarding: dict | None, welcome_message: str | None = None) -> None:
    async def _run() -> None:
        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, business_id, name, plan_tier, status) "
                    "VALUES (CAST(:tid AS UUID), :bid, '极光潮品官方旗舰店', 'enterprise', 'active') "
                    "ON CONFLICT (business_id) DO UPDATE SET name = EXCLUDED.name"
                ).bindparams(tid=str(uuid.uuid4()), bid=_BID)
            )
            await session.execute(
                text("DELETE FROM tenant_configs WHERE business_id = :bid").bindparams(bid=_BID)
            )
            await session.execute(
                text(
                    "INSERT INTO tenant_configs (id, business_id, welcome_message, onboarding_config, status, version) "
                    "VALUES (CAST(:cid AS UUID), :bid, :welcome, CAST(:onboard AS JSONB), 'published', 1)"
                ).bindparams(
                    cid=str(uuid.uuid4()),
                    bid=_BID,
                    welcome=welcome_message,
                    onboard=json.dumps(onboarding, ensure_ascii=False) if onboarding is not None else None,
                )
            )
            await session.commit()

    asyncio.run(_run())


# ---- validate:纯函数,零 DB ----


def test_校验_合法完整配置():
    errors = validate_onboarding_config(
        {
            "welcomeText": "您好,欢迎光临 {brand}!",
            "returningGreeting": "欢迎回来!",
            "quickRepliesTitle": "您可以选：",
            "quickReplies": [{"label": "查物流", "action": "send_message", "payload": {"text": "帮我查物流"}}],
        }
    )
    assert errors == []


def test_校验_空对象与None合法():
    assert validate_onboarding_config(None) == []
    assert validate_onboarding_config({}) == []


def test_校验_未知顶层键显性失败():
    errors = validate_onboarding_config({"welcomeText": "你好", "welcomText": "笔误键"})
    assert any("未知字段" in e and "welcomText" in e for e in errors)


def test_校验_按钮结构与动作约束():
    errors = validate_onboarding_config(
        {
            "quickReplies": [
                {"label": "", "action": "send_message", "payload": {"text": "查物流"}},  # 空 label
                {"label": "上传照片", "action": "trigger_upload", "payload": {}},  # 缺 prompt
                {"label": "爆炸按钮", "action": "delete_all", "payload": {}},  # 非法 action
            ]
        }
    )
    assert len([e for e in errors if "label" in e]) == 1
    assert len([e for e in errors if "prompt" in e]) == 1
    assert len([e for e in errors if "action" in e and "send_message" in e]) == 1


def test_校验_按钮数量与长度上限():
    too_many = {"quickReplies": [{"label": "b", "action": "send_message", "payload": {"text": "t"}}] * 9}
    assert any("quickReplies" in e for e in validate_onboarding_config(too_many))
    too_long = {"welcomeText": "长" * 501}
    assert any("welcomeText" in e for e in validate_onboarding_config(too_long))
    assert any("必须是 JSON 对象" in e for e in validate_onboarding_config(["数组不行"]))


# ---- resolve:三态回落(密封 PG)----


def test_解析_完整配置胜出_占位符按租户名渲染():
    _seed_tenant({"welcomeText": "您好,{brand} 小助手在此!", "returningGreeting": "欢迎回 {brand}~"})
    cfg = asyncio.run(resolve_onboarding_config(_BID))
    assert cfg["welcomeText"] == "您好,极光潮品官方旗舰店 小助手在此!"
    assert cfg["returningGreeting"] == "欢迎回 极光潮品官方旗舰店~"
    assert cfg["brandName"] == "极光潮品官方旗舰店"


def test_解析_空对象是真重置_不被welcome_message列劫持():
    """onboarding_config = {}:PUT 携带即整体覆写,{} = 全字段重置为平台默认
    —— 即使租户有 welcome_message 列也不得劫持(admin 弹窗明确承诺此语义)。"""
    _seed_tenant({}, welcome_message="您好！欢迎来到极光潮品，请问有什么可以帮您？")
    cfg = asyncio.run(resolve_onboarding_config(_BID))
    assert cfg["welcomeText"] == PLATFORM_ONBOARDING["welcomeText"].replace("{brand}", "极光潮品官方旗舰店")
    assert cfg["returningGreeting"] == PLATFORM_ONBOARDING["returningGreeting"].replace(
        "{brand}", "极光潮品官方旗舰店"
    )
    assert cfg["quickReplies"] == PLATFORM_ONBOARDING["quickReplies"]


def test_解析_配置为NULL时welcome_message列中继():
    """onboarding_config 未配置(存量租户):welcome_message 列获得首个消费方,
    仅中继 welcomeText(纯文本已含品牌词,不做占位符替换)。"""
    _seed_tenant(None, welcome_message="您好！欢迎来到极光潮品，请问有什么可以帮您？")
    cfg = asyncio.run(resolve_onboarding_config(_BID))
    assert cfg["welcomeText"] == "您好！欢迎来到极光潮品，请问有什么可以帮您？"
    assert cfg["returningGreeting"] == PLATFORM_ONBOARDING["returningGreeting"].replace(
        "{brand}", "极光潮品官方旗舰店"
    )


def test_解析_部分缺失逐字段独立回落平台默认():
    """只配 quickReplies:配置存在即权威,welcomeText 直接回落平台默认
    (不再看 welcome_message 列),按钮用租户配置。"""
    custom = [{"label": "🎁 查红包", "action": "send_message", "payload": {"text": "查我的红包"}}]
    _seed_tenant({"quickReplies": custom}, welcome_message="极光欢迎您!")
    cfg = asyncio.run(resolve_onboarding_config(_BID))
    assert cfg["welcomeText"] == PLATFORM_ONBOARDING["welcomeText"].replace("{brand}", "极光潮品官方旗舰店")
    assert cfg["quickReplies"] == custom


def test_解析_全缺回落平台默认_无租户行降级品牌名():
    async def _clear() -> None:
        async with get_session() as session:
            await session.execute(text("DELETE FROM tenant_configs WHERE business_id = :b").bindparams(b=_BID))
            await session.execute(text("DELETE FROM tenants WHERE business_id = :b").bindparams(b=_BID))
            await session.commit()

    asyncio.run(_clear())
    cfg = asyncio.run(resolve_onboarding_config("onboard-nobody"))
    assert cfg["brandName"] == "Onboard-nobody 官方旗舰店"
    assert cfg["welcomeText"] == PLATFORM_ONBOARDING["welcomeText"].replace("{brand}", cfg["brandName"])
    assert "转人工" in cfg["quickReplies"][-1]["label"]  # 转人工固定末位


def test_解析_DB异常回落平台默认(monkeypatch):
    class _Boom:
        def __enter__(self):
            raise RuntimeError("db down")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("engine_py.onboarding.get_session", lambda: _Boom())
    cfg = asyncio.run(resolve_onboarding_config("any-bid"))
    assert cfg["welcomeText"] == PLATFORM_ONBOARDING["welcomeText"].replace("{brand}", cfg["brandName"])


def test_入口卡_形状与既有quick_replies链路对齐():
    cfg = asyncio.run(resolve_onboarding_config("onboard-nobody"))
    cards = build_entry_cards(cfg)
    assert len(cards) == 1
    card = cards[0]
    assert card["type"] == "quick_replies"
    assert isinstance(card["data"]["title"], str) and card["data"]["title"]
    for opt in card["data"]["options"]:
        assert set(opt) >= {"label", "action", "payload"}
        assert opt["action"] in {"send_message", "trigger_upload"}
