"""终稿画像/情境记忆注入钉死(persona-hardening 11,规格 spec.md Testing Decisions)。

唯一注入缝 = finish 终稿装配;测试从图状态构造召回输入,桩 chat 模型捕获
最终 prompt 断言外部行为:结构块渲染、scope 标记、条数/单条截断、防复读闸
文本在画像块内、空召回零渲染。严禁断言内部辅助函数调用关系。

裁决溯源:03 号票(注入 finish 单点 / 结构块 + 防复读闸 / episodic 同批 /
阈值 0.55 文档改口);防复读闸原型 = bug#2(画像参与措辞 ≠ 参与检索)。
"""

from __future__ import annotations

import asyncio

import engine_py.graph.nodes.finish as finish_mod
from engine_py.graph.nodes.finish import finish_node

PROFILE_BLOCK = "[USER PROFILE MEMORY]"
EVENTS_BLOCK = "[MEMORY OF PAST EVENTS]"
HISTORY_BLOCK = "[CONVERSATION HISTORY"
ANTICLAIM_MARKER = "MUST NOT claim"


def _fact(text: str, scope: str = "global") -> dict:
    return {"id": f"f-{text[:6]}", "fact": text, "scope": scope, "category": "preference"}


def _event(text: str, importance: int = 5) -> dict:
    return {"id": f"e-{text[:6]}", "event": text, "importanceScore": importance, "scope": "global"}


def _mk_state(**over) -> dict:
    """最小可行终稿状态:business_config 定租户(免 DB 回查),short_memory 非空(免历史回查)。"""
    state = {
        "input": "推荐一双跑鞋",
        "business_config": {"businessId": "nike"},
        "intents": [],
        "task_plan": {"subtasks": []},
        "short_memory": [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "您好,很高兴为您服务"},
        ],
        "global_transitions_count": 0,
        "tool_errors_count": 0,
    }
    state.update(over)
    return state


def _run_capture_prompt(state: dict, monkeypatch) -> str:
    captured: dict = {}

    class _Resp:
        content = "已为您推荐。"

    class _StubChat:
        async def ainvoke(self, prompt: str):
            captured["prompt"] = prompt
            return _Resp()

    monkeypatch.setattr(finish_mod, "get_chat_model", lambda: _StubChat())
    asyncio.run(finish_node(state))
    assert "prompt" in captured, "终稿未走到 LLM 装配分支(提前旁路返回?)"
    return captured["prompt"]


# ---------- 结构块渲染与 scope 标记 ----------


def test_画像召回渲染结构块与scope标记(monkeypatch):
    prompt = _run_capture_prompt(
        _mk_state(
            long_memory_facts=[
                _fact("用户脚长 270mm", scope="global"),
                _fact("偏好 Flyknit 鞋面", scope="tenant"),
            ]
        ),
        monkeypatch,
    )
    assert PROFILE_BLOCK in prompt
    assert "[global] 用户脚长 270mm" in prompt
    assert "[tenant] 偏好 Flyknit 鞋面" in prompt
    # 防复读闸烧在画像块内(bug#2 教训制度化)
    assert ANTICLAIM_MARKER in prompt
    # 注入链序:RAG 之后、历史之前(既有装配链增量,不倒挂)
    assert prompt.find(PROFILE_BLOCK) < prompt.find(HISTORY_BLOCK)


def test_情境事件渲染块且上限3条(monkeypatch):
    events = [_event(f"事件{i}：破损申报") for i in range(5)]
    prompt = _run_capture_prompt(_mk_state(episodic_events=events), monkeypatch)
    assert EVENTS_BLOCK in prompt
    assert "事件0：破损申报" in prompt
    assert "事件2：破损申报" in prompt
    assert "事件3：破损申报" not in prompt  # 召回上限 3,注入面同限不放大
    assert prompt.find(EVENTS_BLOCK) < prompt.find(HISTORY_BLOCK)


def test_双块同批渲染(monkeypatch):
    prompt = _run_capture_prompt(
        _mk_state(
            long_memory_facts=[_fact("偏好轻量跑鞋", scope="tenant")],
            episodic_events=[_event("上次反馈配送破损")],
        ),
        monkeypatch,
    )
    assert PROFILE_BLOCK in prompt and EVENTS_BLOCK in prompt
    assert prompt.find(PROFILE_BLOCK) < prompt.find(EVENTS_BLOCK) < prompt.find(HISTORY_BLOCK)


# ---------- 截断与上限 ----------


def test_画像条数上限5条(monkeypatch):
    facts = [_fact(f"偏好数字{i}号配色", scope="global") for i in range(7)]
    prompt = _run_capture_prompt(_mk_state(long_memory_facts=facts), monkeypatch)
    assert "偏好数字4号配色" in prompt
    assert "偏好数字5号配色" not in prompt


def test_超长单条截断(monkeypatch):
    long_text = "超长偏好" + "细" * 120
    prompt = _run_capture_prompt(_mk_state(long_memory_facts=[_fact(long_text)]), monkeypatch)
    assert long_text not in prompt  # 全文不渲染
    # 截断 80 字:4 字前缀 + 76 个「细」+ 省略号
    assert ("超长偏好" + "细" * 76 + "…") in prompt
    assert prompt.count("细") == 76  # 截断不放大


# ---------- 空召回零渲染 ----------


def test_空召回零渲染(monkeypatch):
    prompt = _run_capture_prompt(_mk_state(long_memory_facts=[], episodic_events=[]), monkeypatch)
    assert PROFILE_BLOCK not in prompt
    assert EVENTS_BLOCK not in prompt


def test_召回升未传入键零渲染(monkeypatch):
    prompt = _run_capture_prompt(_mk_state(), monkeypatch)
    assert PROFILE_BLOCK not in prompt
    assert EVENTS_BLOCK not in prompt


def test_空文本行跳过且编号紧缩(monkeypatch):
    """空文本行不占号:紧随其后的有效行从 1 起(渲染行号无跳空)。"""
    prompt = _run_capture_prompt(
        _mk_state(long_memory_facts=[_fact("  "), _fact("偏好羊毛混纺", scope="global")]),
        monkeypatch,
    )
    assert "1. [global] 偏好羊毛混纺" in prompt


def test_全空文本事实不渲染空壳块(monkeypatch):
    prompt = _run_capture_prompt(
        _mk_state(long_memory_facts=[_fact("  "), _fact("", scope="tenant")]),
        monkeypatch,
    )
    assert PROFILE_BLOCK not in prompt
