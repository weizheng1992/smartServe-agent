"""「继续」确定性重派册(ADR-0013 决策 2,2026-10-10)。

钉死契约:
- 五道闸:非继续词 / 带图 / 有待决议审批(pendingAction)/ 上轮 user 无文本 /
  上轮 assistant 正常完成 —— 任一不过原样放行;
- 命中(上轮 assistant 缺失或失败)→ 改写回上轮用户原问题(user_msgs[-2],
  [-1] 是本轮「继续」自身——网关 chat_turn 先行落库,与 duplicate_intercept
  同一口径);
- 静默重答:改写是纯输入替换,无前缀无旁路,下游全链照常;
- 异常容灾:闸数据不可得一律放行(无异常冷启动)。
"""

from __future__ import annotations

import asyncio
import os

import pytest

# conftest 冻结 DATABASE_URL;本文件先于 engine_py 导入注入环境
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from engine_py.run_agent import AgentJobInput, _maybe_continue_rewrite
from engine_py.triage import rule_matchers

_QUESTION = "天气冷了，推荐一些衣服"


class _StubMemory:
    def __init__(self, msgs: list[dict], task_state: dict | None = None):
        self._msgs = msgs
        self._task_state = task_state

    async def get_messages(self) -> list[dict]:
        return list(self._msgs)


class _StubTaskMemory:
    def __init__(self, task_state: dict | None = None, boom: bool = False):
        self._task_state = task_state
        self._boom = boom

    async def get_task_state(self) -> dict | None:
        if self._boom:
            raise RuntimeError("task memory sealed")
        return self._task_state


def _job(message: str = "继续", image_urls: list[str] | None = None) -> AgentJobInput:
    return AgentJobInput(
        jobId="job_test", threadId="thr_test", message=message, imageUrls=image_urls or []
    )


def _history_missing() -> list[dict]:
    """缺失形态:上轮提问后没有任何 assistant 回复(引擎中断/任务死)。"""
    return [
        {"role": "user", "content": _QUESTION},
        {"role": "user", "content": "继续"},
    ]


def _history_failed() -> list[dict]:
    """失败形态:上轮 assistant 是失败话术(FAILURE_RESPONSE_RE 命中)。"""
    return [
        {"role": "user", "content": _QUESTION},
        {"role": "assistant", "content": "抱歉，请求超时了，请稍后再试"},
        {"role": "user", "content": "继续"},
    ]


def _history_answered() -> list[dict]:
    """正常完成形态:上轮有正常 assistant 回复。"""
    return [
        {"role": "user", "content": _QUESTION},
        {"role": "assistant", "content": "为您找到三款推荐商品…"},
        {"role": "user", "content": "继续"},
    ]


class TestContinueRewriteGates:
    def test_hit_rewrites_to_previous_question_when_answer_missing(self) -> None:
        """正例(缺失形态):上轮无 assistant 回复 → 改写回上轮原问题。"""
        job = _job()
        rewritten = asyncio.run(
            _maybe_continue_rewrite(job, "继续", _StubMemory(_history_missing()), _StubTaskMemory())
        )
        assert rewritten == _QUESTION, f"应改写为上轮问题,实得:{rewritten!r}"

    def test_hit_rewrites_when_last_answer_failed(self) -> None:
        """正例(失败形态):上轮 assistant 是失败话术 → is_failed_response 判缺失。"""
        job = _job()
        rewritten = asyncio.run(
            _maybe_continue_rewrite(job, "接着说", _StubMemory(_history_failed()), _StubTaskMemory())
        )
        assert rewritten == _QUESTION, f"失败回复应视为未答,实得:{rewritten!r}"

    def test_gate_non_continue_word_passes_through(self) -> None:
        """闸① 非「继续」词(哪怕含「继续」子串)绝不劫持。"""
        job = _job("继续推荐便宜的冲锋衣")
        out = asyncio.run(
            _maybe_continue_rewrite(job, job.message, _StubMemory(_history_answered()), _StubTaskMemory())
        )
        assert out == "继续推荐便宜的冲锋衣"

    def test_gate_continue_word_variants_hit(self) -> None:
        """词表规整等值:「继续。」「然后呢?」「请继续」都命中。"""
        for word in ("继续。", "然后呢？", "请继续", " 接着说 "):
            job = _job(word)
            out = asyncio.run(
                _maybe_continue_rewrite(job, word, _StubMemory(_history_missing()), _StubTaskMemory())
            )
            assert out == _QUESTION, f"{word!r} 应命中改写,实得:{out!r}"

    def test_gate_image_turn_passes_through(self) -> None:
        """闸② 带图轮次豁免(图证即新证据)。"""
        job = _job(image_urls=["https://img.test/a.png"])
        out = asyncio.run(
            _maybe_continue_rewrite(job, "继续", _StubMemory(_history_missing()), _StubTaskMemory())
        )
        assert out == "继续"

    def test_gate_pending_action_passes_through(self) -> None:
        """闸③ 有待决议审批(pendingAction)让位 —— HOT-RESUME 契约:审批未
        决议时「继续」必须深规划,不得改写劫持。"""
        plan = {"goal": "退款", "pendingAction": {"tool": "processRefund", "status": "waitingForApproval"}}
        out = asyncio.run(
            _maybe_continue_rewrite(_job(), "继续", _StubMemory(_history_missing()), _StubTaskMemory(task_state=plan))
        )
        assert out == "继续"

    def test_gate_task_memory_boom_passes_through(self) -> None:
        """闸③ 容灾:审批数据不可得 = 无法排除待决议,保守放行不改写。"""
        out = asyncio.run(
            _maybe_continue_rewrite(_job(), "继续", _StubMemory(_history_missing()), _StubTaskMemory(boom=True))
        )
        assert out == "继续"

    def test_gate_previous_user_empty_passes_through(self) -> None:
        """闸④ 上轮 user 无文本(纯图轮等)不可改写。"""
        msgs = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "继续"},
        ]
        out = asyncio.run(_maybe_continue_rewrite(_job(), "继续", _StubMemory(msgs), _StubTaskMemory()))
        assert out == "继续"

    def test_gate_answered_normally_passes_through(self) -> None:
        """闸⑤ 上轮 assistant 正常完成 →「继续」交回 LLM 自由发挥,不改写。"""
        out = asyncio.run(
            _maybe_continue_rewrite(_job(), "继续", _StubMemory(_history_answered()), _StubTaskMemory())
        )
        assert out == "继续"

    def test_history_boom_passes_through(self) -> None:
        """容灾:历史读取异常原样放行(无异常冷启动)。"""
        boom = _StubMemory.__new__(_StubMemory)

        async def _boom():
            raise RuntimeError("memory sealed")

        boom.get_messages = _boom  # type: ignore[method-assign]
        out = asyncio.run(_maybe_continue_rewrite(_job(), "继续", boom, _StubTaskMemory()))
        assert out == "继续"


class TestContinueWordVocab:
    @pytest.mark.parametrize("word", ["继续", "继续说", "请继续", "接着说", "然后呢", "接着讲"])
    def test_vocab_exact_match(self, word: str) -> None:
        assert rule_matchers.is_continue_word(word)

    @pytest.mark.parametrize("text", ["继续。", "然后呢？"])
    def test_vocab_normalized_forms_hit(self, text: str) -> None:
        """规整剥标点后等值命中。"""
        assert rule_matchers.is_continue_word(text)

    @pytest.mark.parametrize("text", ["继续推荐", "帮我继续", "不用继续了"])
    def test_vocab_substring_and_negation_rejected(self, text: str) -> None:
        """子串/否定形接不住(刻意从紧):误劫持有害,漏接无害。"""
        assert not rule_matchers.is_continue_word(text)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
