"""executor fallback 工具选择的实参契约回归(2026-09-26 症状③)。

症状链:fallback LLM 只拿到工具名(无 schema、无用户原话)→ 发明 schema 外
实参 productType/bestSelling → search_products 静默丢弃 → 无过滤全货架检索,
垃圾测试品混进候选池,下游 cart 技能拿垃圾当「店内现货」。

钉死契约:prompt 必须带 [TOOL SCHEMAS](真实参数名)与 [USER ORIGINAL
MESSAGE](参数取值锚定用户原话),并明令禁止发明实参名/严禁把品类词译成英文。
"""

from __future__ import annotations

import asyncio

from engine_py.graph.nodes import step_execution_engine as see


class _CapturingChatModel:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str):
        self.prompts.append(prompt)

        class _Resp:
            content = "NONE"

        return _Resp()


def _build_prompt(monkeypatch) -> str:
    fake = _CapturingChatModel()
    monkeypatch.setattr(see, "get_chat_model", lambda: fake)
    # 本缝只测 fallback prompt 装配,fast-path 一律放行到 LLM 兜底
    monkeypatch.setattr(see, "try_match_executor_fast_path", lambda *a, **k: None)

    state = {
        "input": "把销量最好的裤子放到购物车，买2件",
        "thread_id": "dbg_fb_thread",
    }
    plan = {
        "subtasks": [
            {"id": "s1", "description": "Search the catalog for the product type the customer referred to", "status": "planned"}
        ]
    }
    asyncio.run(
        see._execute_single_step_core(
            state=state,
            current_plan=plan,
            index_to_run=0,
            allowed_tools=["searchProducts", "queryProductRanking"],
            short_memory=[],
            history_context="",
        )
    )
    assert len(fake.prompts) == 1, f"fallback 须恰好一次 LLM 调用,实际 {len(fake.prompts)}"
    return fake.prompts[0]


class TestFallbackPromptCarriesContract:
    def test_tool_schemas_block_present(self, monkeypatch):
        """prompt 必须携带真实工具 schema —— 实参名有据可依。"""
        prompt = _build_prompt(monkeypatch)
        assert "[TOOL SCHEMAS]" in prompt
        assert '"searchProducts"' in prompt
        assert '"query"' in prompt, "searchProducts 的真实参数名 query 必须在 schema 里"
        assert '"category"' in prompt

    def test_user_original_message_present(self, monkeypatch):
        """参数取值必须锚定用户原话(英文步骤描述是有损转译)。"""
        prompt = _build_prompt(monkeypatch)
        assert "[USER ORIGINAL MESSAGE]" in prompt
        assert "销量最好的裤子" in prompt

    def test_no_invented_args_rule(self, monkeypatch):
        """必须明令禁止发明实参名(静默丢弃→无过滤检索的事故通道)。"""
        prompt = _build_prompt(monkeypatch)
        assert "never invent argument names" in prompt
        assert "silently dropped" in prompt

    def test_no_english_translation_rule(self, monkeypatch):
        """品类取值必须引用用户原话,严禁译成英文(实弹 productType=pants 通道)。"""
        prompt = _build_prompt(monkeypatch)
        assert "do NOT translate" in prompt


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
