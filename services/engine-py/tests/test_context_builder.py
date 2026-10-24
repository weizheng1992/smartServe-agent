"""context_builder 单测 —— 历史 token 预算 + 滚动摘要 + 结构化行格式。

拷问轮决议(2026-09-21):AI_HISTORY_BUDGET_TOKENS 默认 2000 字符近似,按整轮
裁剪不切半轮;溢出懒触发摘要(复用 get_chat_model,max_tokens≈300);行格式
[T{n} MM-dd HH:mm] Role(无时间戳回退 [T{n}]);builder 纯函数,LLM 只在
summarize_overflow 一处。
"""

from __future__ import annotations

import pytest


def _msg(role: str, content: str, created_at: str | None = None) -> dict:
    m = {"role": role, "content": content}
    if created_at:
        m["created_at"] = created_at
    return m


class TestEstimateTokens:
    def test_char_approximation(self):
        from engine_py.memory.context_builder import estimate_tokens

        assert estimate_tokens("") == 0
        assert estimate_tokens("你好世界") == 4
        assert estimate_tokens("order 123") == 9


class TestBuildHistoryBlock:
    def test_turn_numbers_and_timestamps(self):
        from engine_py.memory.context_builder import build_history_block

        msgs = [
            _msg("user", "你好", "2026-09-21T06:00:00+00:00"),
            _msg("assistant", "您好", "2026-09-21T06:00:05+00:00"),
        ]
        out = build_history_block(msgs, budget=10_000)
        assert "[T1 09-21 06:00] Customer:" in out["block"]
        assert "[T2 09-21 06:00] Agent:" in out["block"]
        assert out["trimmed"] is False and out["overflow"] == []
        assert out["kept_count"] == 2

    def test_turn_number_without_timestamp_falls_back(self):
        from engine_py.memory.context_builder import build_history_block

        out = build_history_block([_msg("user", "在吗")], budget=10_000)
        assert "[T1] Customer:" in out["block"]

    def test_budget_trims_oldest_first_keeps_chronology(self):
        from engine_py.memory.context_builder import build_history_block

        msgs = [
            _msg("user", "A" * 60),
            _msg("assistant", "B" * 60),
            _msg("user", "C" * 60),
            _msg("assistant", "D" * 10),
        ]
        out = build_history_block(msgs, budget=80)  # 只装得下最后一两条
        assert out["trimmed"] is True
        assert out["kept_count"] < 4
        # 最老的先溢出
        assert msgs[0] in out["overflow"] and msgs[1] in out["overflow"]
        # 保留段保持时间正序,且含最新行
        assert "D" * 10 in out["block"]
        block_lines = [ln for ln in out["block"].splitlines() if ln.startswith("[T")]
        assert block_lines == sorted(block_lines) or len(block_lines) == 1

    def test_under_budget_no_overflow(self):
        from engine_py.memory.context_builder import build_history_block

        msgs = [_msg("user", "短" * 5), _msg("assistant", "好" * 5)]
        out = build_history_block(msgs, budget=10_000)
        assert out["overflow"] == [] and out["trimmed"] is False
        assert out["kept_count"] == 2

    def test_summary_section_rendered(self):
        from engine_py.memory.context_builder import build_history_block

        out = build_history_block([_msg("user", "在吗")], summary="顾客之前咨询过退款。", budget=10_000)
        assert out["block"].startswith("[EARLIER SUMMARY]:")
        assert "顾客之前咨询过退款。" in out["block"]

    def test_no_summary_no_header(self):
        from engine_py.memory.context_builder import build_history_block

        out = build_history_block([_msg("user", "在吗")], budget=10_000)
        assert "[EARLIER SUMMARY]" not in out["block"]

    def test_invalid_rows_skipped(self):
        from engine_py.memory.context_builder import build_history_block

        msgs = [
            _msg("user", ""),
            _msg("assistant", "undefined"),
            _msg("user", None),
            _msg("user", "真实问题"),
        ]
        out = build_history_block(msgs, budget=10_000)
        assert out["kept_count"] == 1
        assert "真实问题" in out["block"]

    def test_budget_never_zero_rows(self):
        """预算再小也至少保留最新一轮(否则上下文全靠摘要,当轮反而无历史)。"""
        from engine_py.memory.context_builder import build_history_block

        msgs = [_msg("user", "X" * 500), _msg("assistant", "Y" * 500)]
        out = build_history_block(msgs, budget=10)
        assert out["kept_count"] >= 1

    def test_task_state_section_leads_block(self):
        """任务层段前置于装配面(docs/multi-turn-task-state.md P0-1):渲染在
        [EARLIER SUMMARY] 与历史轮之前 —— planner/finish 消费 block 的首个段。"""
        from engine_py.memory.context_builder import build_history_block

        out = build_history_block(
            [_msg("user", "订当天的酒店")],
            summary="顾客之前咨询过高铁。",
            task_state_line="[TASK STATE] 当前任务:上海行程 ｜ 关键实体:date=周三",
            budget=10_000,
        )
        lines = out["block"].splitlines()
        assert lines[0].startswith("[TASK STATE]")
        assert "[EARLIER SUMMARY]:" in lines[1]
        assert "[T1" in lines[3]

    def test_no_task_state_no_header(self):
        from engine_py.memory.context_builder import build_history_block

        out = build_history_block([_msg("user", "在吗")], budget=10_000)
        assert "[TASK STATE]" not in out["block"]

    def test_task_state_line_counts_against_budget(self):
        """任务层段受同一预算管控(P0-1 规格/code-review 裁定):先扣自身成本
        再装轮;同预算下无任务行能装两轮、有任务行只装一轮 —— 扣减真实生效。"""
        from engine_py.memory.context_builder import build_history_block

        msgs = [_msg("user", "X" * 20), _msg("assistant", "Y" * 20)]
        line = "[TASK STATE] " + "字" * 30  # 43 字符
        without = build_history_block(msgs, budget=100)
        assert without["kept_count"] == 2
        out = build_history_block(msgs, task_state_line=line, budget=100)
        assert out["kept_count"] == 1 and out["trimmed"] is True
        assert out["block"].startswith("[TASK STATE]")

    def test_append_only_prefix_stability(self):
        """KV-cache 前缀纪律(docs/multi-turn-task-state.md P2-2,Manus 裁决):
        预算内新轮只追加 —— 上一轮的装配产物必须是本轮产物的严格前缀,任何
        重排/改写都是缓存命中率的敌人。"""
        from engine_py.memory.context_builder import build_history_block

        msgs = [
            _msg("user", "订周三的酒店", "2026-10-24T09:00:00"),
            _msg("assistant", "好的", "2026-10-24T09:00:10"),
            _msg("user", "换成周四", "2026-10-24T09:01:00"),
        ]
        line = "[TASK STATE] 当前任务:上海行程 ｜ 关键实体:date=周四"
        block3 = build_history_block(msgs, task_state_line=line, budget=10_000)["block"]
        block4 = build_history_block([*msgs, _msg("assistant", "已改", "2026-10-24T09:01:30")], task_state_line=line, budget=10_000)["block"]
        assert block4.startswith(block3), "预算内追加必须保持前缀稳定"

    def test_determinism_same_inputs_same_block(self):
        """同输入同产物(纯函数无时钟/随机注入)—— 可缓存性的前提。"""
        from engine_py.memory.context_builder import build_history_block

        msgs = [_msg("user", "在吗"), _msg("assistant", "在的")]
        a = build_history_block(msgs, summary="s", task_state_line="[TASK STATE] x", budget=10_000)["block"]
        b = build_history_block(list(msgs), summary="s", task_state_line="[TASK STATE] x", budget=10_000)["block"]
        assert a == b


class TestSummarizeOverflow:
    @pytest.mark.asyncio
    async def test_merges_previous_summary_and_overflow(self, monkeypatch):
        import engine_py.memory.context_builder as cb

        captured: dict = {}

        class _Resp:
            content = "顾客先前咨询退款与运单,已给单号。"

        class _StubChat:
            def bind(self, **kwargs):
                return self

            async def ainvoke(self, prompt):
                captured["prompt"] = prompt
                return _Resp()

        monkeypatch.setattr(cb, "get_chat_model", lambda: _StubChat())
        overflow = [_msg("user", "我的订单 AURORA-ORD-2026-9999 退款了"), _msg("assistant", "已受理")]
        out = await cb.summarize_overflow("旧摘要:顾客买过冲锋衣。", overflow)
        assert out == "顾客先前咨询退款与运单,已给单号。"
        assert "旧摘要" in captured["prompt"] and "AURORA-ORD-2026-9999" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_previous_summary(self, monkeypatch):
        import engine_py.memory.context_builder as cb

        class _Boom:
            async def ainvoke(self, prompt):
                raise RuntimeError("网络炸了")

        monkeypatch.setattr(cb, "get_chat_model", lambda: _Boom())
        overflow = [_msg("user", "你好")]
        out = await cb.summarize_overflow("旧摘要:顾客买过冲锋衣。", overflow)
        assert out == "旧摘要:顾客买过冲锋衣。"

    @pytest.mark.asyncio
    async def test_empty_overflow_returns_previous(self, monkeypatch):
        import engine_py.memory.context_builder as cb

        monkeypatch.setattr(cb, "get_chat_model", lambda: (_ for _ in ()).throw(AssertionError("不应调用")))
        assert await cb.summarize_overflow("旧摘要", []) == "旧摘要"
        assert await cb.summarize_overflow(None, []) is None
