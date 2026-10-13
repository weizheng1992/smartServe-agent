"""上下文子系统契约钉(2026-09-21 拷问轮决议)—— 三条不变量:

① 记忆召回租户过滤必须在 SQL 层(候选窗口不被他租行挤占);
   Python 侧 _tenant_visible 仅为防御纵深。
② run_agent 两落库路径(有输出/无输出)都必须 upsert task_memory 并携带
   historySummary —— 挂起恢复与滚动摘要的跨轮持久化依赖它。
③ 历史超预算必须产出非空摘要(compress/summarize 对 stub 回归免疫)。
"""

from __future__ import annotations

import inspect

import pytest


class TestSqlLayerTenantFilter:
    def test_recall_queries_reference_sql_scope_condition(self):
        """召回函数的查询构造必须引用 tenant_scope_condition(① 的 SQL 层证据)。"""
        from engine_py.memory import episodic_memory, long_memory

        for fn in (long_memory.LongMemory.search_relevant_facts, episodic_memory.EpisodicMemory.retrieve_events):
            src = inspect.getsource(fn)
            assert "tenant_scope_condition(" in src, (
                f"{fn.__qualname__} 的召回 WHERE 未引用 SQL 层租户条件 —— 候选窗口会被他租行挤占"
            )

    def test_tenant_condition_semantics(self):
        """条件语义钉:有效租户只放本租 tenant 行;ecommerce 缺省放空白 + ecommerce。"""
        from sqlalchemy import Column, MetaData, String, Table

        from engine_py.memory.tenant_scope import tenant_scope_condition

        meta = MetaData()
        tbl = Table(
            "t", meta,
            Column("scope", String(20)),
            Column("business_id", String(50)),
        )
        # 编译为 SQL 文本断言语义(不同入参 → 不同 business_id 谓词)
        sql_valid = str(tenant_scope_condition(tbl.c, "aurora").compile(compile_kwargs={"literal_binds": True}))
        sql_blank = str(tenant_scope_condition(tbl.c, "ecommerce").compile(compile_kwargs={"literal_binds": True}))
        assert "business_id = :business_id_1" in sql_valid or "aurora" in sql_valid
        assert "ecommerce" in sql_blank and "IS NULL" in sql_blank


class TestTaskMemorySettlePersistence:
    def test_both_settle_paths_persist_history_summary(self):
        """② 收口函数(_settle_turn)两条落库路径都须 save_task_state 且带 historySummary;
        run_agent 装载面必须回读上轮摘要。"""
        import importlib

        ra = importlib.import_module("engine_py.run_agent")

        settle_src = inspect.getsource(ra._settle_turn)
        assert settle_src.count("task_memory.save_task_state(") >= 2, "有输出/无输出两路径都必须落任务记忆"
        assert settle_src.count('"historySummary":') >= 2, "两条路径都必须携带滚动摘要(跨轮持久化)"
        assert 'saved_state.get("historySummary")' in inspect.getsource(ra), "装载面必须回读上轮摘要"


class TestSummaryNeverEmptyWhenOverBudget:
    @pytest.mark.asyncio
    async def test_compress_real_output_not_stub(self, monkeypatch):
        """③ ShortMemory.compress 严禁退回常量 stub;LLM 失败也要确定性拼接兜底。"""
        from engine_py.memory import ShortMemory

        class _Boom:
            async def ainvoke(self, prompt):
                raise RuntimeError("离线")

        import engine_py.memory.context_builder as cb

        monkeypatch.setattr(cb, "get_chat_model", lambda: _Boom())
        sm = ShortMemory("t-compact")
        out = await sm.compress([
            {"role": "user", "content": "我的订单 AURORA-ORD-2026-9999 退款了"},
            {"role": "assistant", "content": "已受理,3 个工作日到账"},
        ])
        assert out and "Summary of compressed" not in out, "compress 退回 stub 或空输出"
        assert "AURORA-ORD-2026-9999" in out, "离线兜底拼接必须保留关键事实(单号)"

    @pytest.mark.asyncio
    async def test_over_budget_block_carries_summary_header(self, monkeypatch):
        """超预算 → 溢出摘要化 → block 渲染 [EARLIER SUMMARY](run_agent 集成语义的 builder 级钉)。"""
        from engine_py.memory.context_builder import build_history_block, summarize_overflow

        class _StubChat:
            def bind(self, **kwargs):
                return self

            async def ainvoke(self, prompt):
                class _R:
                    content = "早期顾客咨询过退款。"

                return _R()

        import engine_py.memory.context_builder as cb

        monkeypatch.setattr(cb, "get_chat_model", lambda: _StubChat())
        msgs = [
            {"role": "user", "content": f"历史消息第 {i} 条" + "长" * 80}
            for i in range(1, 31)
        ]
        built = build_history_block(msgs, summary=None, budget=500)
        assert built["trimmed"], "30 条长历史必须触发裁剪"
        summary = await summarize_overflow(None, built["overflow"])
        assert summary, "溢出摘要不得为空"
        final = build_history_block(msgs, summary=summary, budget=500)
        assert "[EARLIER SUMMARY]:" in final["block"], "摘要段必须渲染进历史块"
