"""规则前置层 Stage 专册(2026-10-01 夜审补缺,此前零直接测试)。

钉死两层:
1. RuleWhitelistStage(`triage/stages/rule_whitelist.py`)四条零 LLM 旁路 ——
   空消息(带图豁免)/ 纯符号 / 超长 >1000 / 退出指令,加问候同源罐头与
   转人工直达终局;旁路裁决 = route_key + 罐头文案,零 LLM 调用;
2. ConfirmationResumeStage(`triage/stages/confirmation_resume.py`)确认轮
   动作恢复 —— pendingAction + 肯定确认语 → address_manage 终局(参数透传),
   无待执行动作 / 非确认语一律 passthrough;恢复时发用户态进度事件。

Stage 面单测:engine 协作点(handle_immediate_bypass / onboarding 装配 /
event_bus.emit_status)一律 monkeypatch,不触 DB / Redis / LLM。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.triage import intent_triage_engine as engine_module
from engine_py.triage.intent_triage_engine import IntentTriageEngine
from engine_py.triage.stages import ConfirmationResumeStage, RuleWhitelistStage
from engine_py.triage.stages.context import StageContext


def _ctx(input_text: str, state: dict | None = None, clean_input: str | None = None) -> StageContext:
    text = input_text
    return StageContext(
        state=state if state is not None else {"input": text},
        thread_id="t-stage-1",
        input_text=text,
        clean_input=clean_input if clean_input is not None else text,
        tenant_id="aurora",
        history_msgs=[],
        engine=IntentTriageEngine,
    )


@pytest.fixture()
def bypass_recorder(monkeypatch):
    """桩掉旁路出口,捕获 route_key / 罐头文案 / 卡片(不触 log_intent_to_db)。"""
    calls: dict = {}

    async def _fake(state, route_key, reply_text, intents, method, confidence, damage_assessment=None, cards=None, **kwargs):
        calls.update(route_key=route_key, reply=reply_text, intents=intents, cards=cards)
        return {"intents": intents, "output": reply_text, "route_key": route_key, "cards": cards or []}

    monkeypatch.setattr(IntentTriageEngine, "handle_immediate_bypass", _fake)
    return calls


# ---- 1. RuleWhitelistStage:四条零 LLM 旁路 + 问候同源 + 转人工 ----


def test_空消息旁路(bypass_recorder):
    verdict = asyncio.run(RuleWhitelistStage.judge(_ctx("")))
    assert verdict.terminal and bypass_recorder["route_key"] == "rule_empty"
    assert "空消息" in bypass_recorder["reply"]


def test_空文本带图不按空消息旁路(bypass_recorder):
    """多模态豁免:带图轮次图证未消费前不得关闭会话。"""
    verdict = asyncio.run(RuleWhitelistStage.judge(_ctx("", state={"input": "", "image_urls": ["x.png"]})))
    assert not verdict.terminal


def test_纯符号旁路(bypass_recorder):
    verdict = asyncio.run(RuleWhitelistStage.judge(_ctx("!!!@@@###")))
    assert verdict.terminal and bypass_recorder["route_key"] == "rule_symbols"


def test_超长输入旁路(bypass_recorder):
    verdict = asyncio.run(RuleWhitelistStage.judge(_ctx("问" * 1001)))
    assert verdict.terminal and bypass_recorder["route_key"] == "rule_length_limit"


def test_退出指令旁路(bypass_recorder):
    verdict = asyncio.run(RuleWhitelistStage.judge(_ctx("再见", clean_input="再见")))
    assert verdict.terminal and bypass_recorder["route_key"] == "rule_exit_conversation"
    assert bypass_recorder["intents"][0]["intent"] == "general_query"


def test_问候消费租户onboarding同源罐头(bypass_recorder, monkeypatch):
    async def _fake_onboarding(tenant_id):
        return {"welcomeText": f"欢迎来到{tenant_id}商城!", "quickReplies": ["查订单", "退换货"]}

    def _fake_cards(onboarding):  # 同步:rule_whitelist 调用点无 await
        return [{"type": "quick_replies", "items": onboarding["quickReplies"]}]

    monkeypatch.setattr(engine_module, "resolve_onboarding_config", _fake_onboarding)
    monkeypatch.setattr(engine_module, "build_entry_cards", _fake_cards)

    verdict = asyncio.run(RuleWhitelistStage.judge(_ctx("你好", clean_input="你好")))
    assert verdict.terminal and bypass_recorder["route_key"] == "rule_greeting"
    assert bypass_recorder["reply"] == "欢迎来到aurora商城!"
    assert bypass_recorder["cards"] == [{"type": "quick_replies", "items": ["查订单", "退换货"]}]


def test_转人工直达终局(bypass_recorder):
    verdict = asyncio.run(RuleWhitelistStage.judge(_ctx("我要转人工客服")))
    assert verdict.terminal
    assert verdict.result["intents"][0]["intent"] == "human_escalation"
    assert "route_key" not in bypass_recorder, "转人工不走 bypass 出口,直 达终局组装"


def test_普通问题passthrough(bypass_recorder):
    verdict = asyncio.run(RuleWhitelistStage.judge(_ctx("我的订单到哪了")))
    assert not verdict.terminal and not bypass_recorder


# ---- 2. ConfirmationResumeStage:确认轮动作恢复 ----


def _state_with_pending(tool: str = "set_default_address", **extra) -> dict:
    return {
        "input": "是的",
        "task_plan": {"pendingAction": {"tool": tool, "args": {"addressId": "addr-9"}}},
        **extra,
    }


def test_确认语恢复待执行动作():
    verdict = asyncio.run(ConfirmationResumeStage.judge(_ctx("是的", state=_state_with_pending())))
    assert verdict.terminal
    intent = verdict.result["intents"][0]
    assert intent["intent"] == "address_manage" and intent["confidence"] == 1.0
    assert intent["entities"]["addressAction"] == "set_default_address"
    assert intent["entities"]["addressId"] == "addr-9", "上轮参数必须原样透传"


def test_确认语但无待执行动作passthrough():
    verdict = asyncio.run(ConfirmationResumeStage.judge(_ctx("是的", state={"input": "是的"})))
    assert not verdict.terminal


def test_非确认语不恢复():
    verdict = asyncio.run(ConfirmationResumeStage.judge(_ctx("随便看看", state=_state_with_pending())))
    assert not verdict.terminal


def test_恢复时发进度事件(monkeypatch):
    emitted: list[tuple] = []

    async def _fake_emit(job_id, message, node=None, **kwargs):
        emitted.append((job_id, message))

    monkeypatch.setattr("engine_py.event_bus.emit_status", _fake_emit)
    verdict = asyncio.run(
        ConfirmationResumeStage.judge(_ctx("确认", state=_state_with_pending(job_id="job-resume-1")))
    )
    assert verdict.terminal
    assert emitted and emitted[0][0] == "job-resume-1" and "恢复" in emitted[0][1]
