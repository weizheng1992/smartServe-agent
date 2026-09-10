"""问候旁路同源改造(new-user-onboarding D)。

钉死四件事:
1. 词表合一:run_agent 极速旁路与 triage 规则层共用 QUICK_GREETING_WORDS
   单一来源(GREETING_RE 由词表派生),旧两表各自的词并集全命中、
   非问候语不误伤;
2. 罐头回复消费 onboarding_config:极速旁路回 welcomeText 并下发能力
   入口 quick_replies 卡(带卡落库,刷新/历史还原可见);
3. 零 LLM 与所有权口径不回退:旁路全程零模型调用,用户行仍归网关
   (引擎零写),assistant 行带 cards 落库;
4. triage Step 1 规则层(纵深防御兜底)同样消费那份配置,
   留痕 method=rule_greeting 不变。
"""

from __future__ import annotations

import asyncio
import importlib

import pytest
from sqlalchemy import select

from engine_py.db import Message
from engine_py.triage import rule_matchers
from engine_py.triage.semantic_cache import strip_punctuation_for_greeting

pytestmark = pytest.mark.usefixtures("pg_factory")


class _StubGraph:
    async def ainvoke(self, _state):
        raise AssertionError("问候旁路必须零 LLM/零图执行 —— 图被调到即回归")


class _NoopEpisodic:
    def __init__(self, *args, **kwargs):
        pass

    async def add_event(self, *args, **kwargs):
        return None

    async def retrieve_events(self, *args, **kwargs):
        return []


class _NoopLong:
    def __init__(self, *args, **kwargs):
        pass

    async def extract_and_store_fact(self, *args, **kwargs):
        return None

    async def search_relevant_facts(self, *args, **kwargs):
        return []


@pytest.fixture(autouse=True)
def _isolate_llm_and_memory(monkeypatch):
    run_agent_module = importlib.import_module("engine_py.run_agent")
    monkeypatch.setattr(run_agent_module, "EpisodicMemory", _NoopEpisodic)
    monkeypatch.setattr(run_agent_module, "LongMemory", _NoopLong)
    monkeypatch.setattr(run_agent_module, "build_graph", lambda: _StubGraph())
    yield


def _run(thread_id: str, message: str) -> dict:
    run_agent_module = importlib.import_module("engine_py.run_agent")
    job = run_agent_module.AgentJobInput(
        job_id="",  # 空 job_id:跳过 Redis 事件发布,零外联
        threadId=thread_id,
        userId="CUST-GREET-ONB",
        businessId="aurora",
        message=message,
    )
    return asyncio.run(run_agent_module.run_agent(job))


async def _fetch_assistant_rows(thread_id: str) -> list[Message]:
    from engine_py.db import get_session

    async with get_session() as session:
        rows = (
            await session.execute(
                select(Message).where(Message.thread_id == thread_id, Message.role == "assistant")
            )
        ).scalars().all()
        # 触发懒加载列(cards JSONB 由 asyncpg 原生解码,提前物化防出会话后丢引用)
        _ = [(r.content, r.cards) for r in rows]
        return rows


# ---- 1. 词表合一(纯函数)----


@pytest.mark.parametrize(
    "word",
    sorted(rule_matchers.QUICK_GREETING_WORDS),
)
def test_词表全词两层判定一致(word):
    """词表每一词在两层(run_agent 规整精确匹配 × triage 正则)都命中。"""
    assert rule_matchers.is_quick_greeting(word)
    assert rule_matchers.is_greeting(strip_punctuation_for_greeting(word))


def test_旧两表并集收口():
    """旧 run_agent 独有的身份问句与旧 triage 独有的时段问候都已入统一表。"""
    words = rule_matchers.QUICK_GREETING_WORDS
    # 旧 run_agent 表("who are you" 是其带空格死词条,统一为规整后形态)
    assert {"你是谁", "你是机器人吗", "whoareyou"} <= words
    assert {"早上好", "下午好", "晚上好", "哈拉"} <= words  # 旧 triage 表


@pytest.mark.parametrize(
    "not_greeting",
    ["你好吗最近", "帮我查一下订单", "hi你好这是一段长句", "", "转人工"],
)
def test_非问候语不误伤(not_greeting):
    assert not rule_matchers.is_quick_greeting(not_greeting)
    assert not rule_matchers.is_greeting(strip_punctuation_for_greeting(not_greeting))


# ---- 2+3. 极速旁路:同源文案 + 入口卡 + 零LLM/零用户行 ----


def test_旁路回欢迎文案并带入口卡落库():
    thread_id = "onb_greet_welcome_card"
    result = _run(thread_id, "你好")

    # 引擎测试库无 aurora 租户行 → 平台默认文案(品牌降级渲染)
    assert "智能客服小助手" in result["output"]
    cards = result.get("cards") or []
    assert cards and cards[0]["type"] == "quick_replies"
    options = cards[0]["data"]["options"]
    assert 3 <= len(options) <= 5
    assert "转人工" in options[-1]["label"]

    rows = asyncio.run(_fetch_assistant_rows(thread_id))
    assert len(rows) == 1
    assert "智能客服小助手" in rows[0].content
    persisted_cards = rows[0].cards
    assert persisted_cards and persisted_cards[0]["type"] == "quick_replies"  # 带卡落库


def test_身份问句与时段问候都走同一条旁路():
    """词表合一后,「你是谁」(旧 run_agent)与「早上好」(旧 triage 独有,
    此前会漏进 triage 层)统一被极速旁路拦截。"""
    for msg in ("你是谁", "早上好"):
        result = _run(f"onb_greet_unified_{msg}", msg)
        assert "智能客服小助手" in result["output"], msg
        assert result.get("cards"), msg


# ---- 4. triage Step 1 规则层(纵深防御兜底)同源消费配置 ----


class _FakeShortMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_messages(self) -> list:
        return []


class _FakeTaskMemory:
    def __init__(self, thread_id: str) -> None:
        pass

    async def get_task_state(self) -> dict | None:
        return None

    async def save_task_state(self, state: dict) -> None:
        return None


def test_triage层问候兜底同源消费配置(monkeypatch):
    """run_agent 极速旁路未拦到时(纵深防御),triage Step 1 规则层罐头回复
    消费同一份 resolve_onboarding_config —— 自定义 welcomeText 与入口卡
    原样下发,留痕 method=rule_greeting 不变。"""
    from engine_py.triage import intent_triage_engine as triage_mod
    from engine_py.triage.intent_triage_engine import IntentTriageEngine

    custom = {
        "businessId": "aurora",
        "brandName": "极光潮品",
        "welcomeText": "自定义引导语GREETCFG",
        "returningGreeting": "自定义轻问候",
        "quickRepliesTitle": "请选择：",
        "quickReplies": [
            {"label": "🎁 查红包", "action": "send_message", "payload": {"text": "查我的红包"}}
        ],
    }

    async def _fake_resolve(business_id: str = "ecommerce"):
        return custom

    monkeypatch.setattr(triage_mod, "resolve_onboarding_config", _fake_resolve)
    monkeypatch.setattr(triage_mod, "ShortMemory", _FakeShortMemory)
    monkeypatch.setattr(triage_mod, "TaskMemory", _FakeTaskMemory)

    calls: list[dict] = []

    async def _recording_log(thread_id, input_text, intents, method, confidence, **kwargs):
        calls.append({"method": method, "confidence": confidence, **kwargs})

    monkeypatch.setattr(IntentTriageEngine, "log_intent_to_db", _recording_log)

    state = {
        "thread_id": "thread_greet_triage_cfg",
        "user_id": "u_greet_triage",
        "input": "你好",
        "image_urls": [],
        "input_embedding": [],
        "business_config": {"businessId": "aurora"},
    }
    result = asyncio.run(IntentTriageEngine.process(state))

    assert "自定义引导语GREETCFG" in result["output"]
    cards = result.get("cards") or []
    assert cards and cards[0]["type"] == "quick_replies"
    assert cards[0]["data"]["options"][0]["label"] == "🎁 查红包"
    # 留痕口径:method=rule(规则层),路由键 rule_greeting 落 arbitration_reason
    assert len(calls) == 1
    assert calls[0]["method"] == "rule"
    assert calls[0]["arbitration_reason"] == "rule_greeting"
