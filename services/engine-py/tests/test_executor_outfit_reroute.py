"""executor 搭配语义守卫回归(2026-09-29 实弹「之前只有装备,现在只有衣服」)。

症状链:同句「搭配一套…装备和衣服」在 9-27 走技能路径出双族+合计预算,
9-29 却只推 2 件短袖衬衫 —— 工具选择两条来路(fast-path 关键词 / fallback
LLM)都可能把搭配请求写成 searchProducts 工具子任务(query 自拟单脚),工具
路径没有技能 SOP 的搭配族补脚/交错合并/合计预算,必然单族输出。

钉死契约:searchProducts 命中搭配形态(搭配/一套/套装 × 衣着锚词)一律在
物理调度前改路由 skill_shopping_guide;判据直接引用技能类属性正则(单一事
实源,与技能内补脚永不漂移),不依赖 LLM 自觉。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.graph.nodes import step_execution_engine as see
from engine_py.tools_registry.mall_domain import MallDomainService

_OUTFIT_INPUT = "我打算出去旅行，给我搭配一套出去旅行的装备和衣服，按照现在的季节，金额不超过2000"

_DUAL_FAMILY = [
    {"id": "g1", "name": "极光 超轻铝合金双人帐篷", "price": 599.0, "stock": 12, "description": "露营帐篷", "specs": {}, "category": "camping"},
    {"id": "g2", "name": "极光 三季保暖睡袋", "price": 329.0, "stock": 20, "description": "露营睡袋", "specs": {}, "category": "camping"},
    {"id": "c1", "name": "极光 速干透气防晒衬衫", "price": 199.0, "stock": 30, "description": "旅行衬衫", "specs": {}, "category": "apparel"},
    {"id": "c2", "name": "极光 弹力休闲长裤", "price": 249.0, "stock": 25, "description": "旅行长裤", "specs": {}, "category": "apparel"},
]

_SHOES_ONLY = [
    {"id": "s1", "name": "极光 缓震透气跑步鞋", "price": 399.0, "stock": 40, "description": "跑鞋", "specs": {}, "category": "running_shoes"},
]


class _FixedToolChoiceModel:
    """模拟 fallback LLM 把子任务写成 searchProducts 工具(实弹分叉形态)。"""

    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def ainvoke(self, prompt: str):
        class _Resp:
            content = self._payload

        return _Resp()


def _run_step(monkeypatch: pytest.MonkeyPatch, user_input: str, llm_payload: str, products: list[dict]) -> dict:
    calls: list[dict] = []

    async def fake_search(params: dict) -> dict:
        calls.append(params)
        return {"total": len(products), "products": products}

    async def fake_overview() -> list[dict]:
        return []

    monkeypatch.setattr(MallDomainService, "search_products", staticmethod(fake_search))
    monkeypatch.setattr(MallDomainService, "get_shelf_overview", staticmethod(fake_overview))
    # 本缝只测 dispatch 守卫,fast-path 一律放行到 fallback LLM(实弹分叉形态)
    monkeypatch.setattr(see, "try_match_executor_fast_path", lambda *a, **k: None)
    monkeypatch.setattr(see, "get_chat_model", lambda: _FixedToolChoiceModel(llm_payload))

    res = asyncio.run(
        see._execute_single_step_core(
            state={"input": user_input, "thread_id": "t_outfit_guard", "user_id": "u1", "business_id": "ecommerce"},
            current_plan={"subtasks": [{"id": "s1", "description": "Search the catalog for products", "status": "planned"}]},
            index_to_run=0,
            allowed_tools=["searchProducts", "skill_shopping_guide"],
            short_memory=[],
            history_context="",
        )
    )
    res["_search_calls"] = calls
    return res


class TestOutfitRerouteGuard:
    def test_outfit_input_via_search_products_reroutes_to_guide_skill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """搭配句被写成 searchProducts 子任务 → 物理调度前改路由技能,双族在场。"""
        res = _run_step(
            monkeypatch,
            _OUTFIT_INPUT,
            '{"toolName": "searchProducts", "args": {"query": "短袖衬衫"}}',
            _DUAL_FAMILY,
        )
        assert res["toolExecutedName"] == "skill_shopping_guide", (
            f"搭配形态必须改路由 ShoppingGuideSkill,实弹症状是工具路径单脚只推单族,实际 {res['toolExecutedName']}"
        )
        output = res["updatedStep"]["result"].get("output") or ""
        assert "帐篷" in output and "衬衫" in output, f"双族必须同场,实际输出:{output[:200]}"
        # 改路由后检索由技能承接:整句 userInput 进技能,而非 LLM 自拟单词
        assert res["_search_calls"], "技能路径必须发起检索"
        assert res["_search_calls"][0].get("query") == _OUTFIT_INPUT

    def test_plain_search_stays_on_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无搭配形态的普通检索不走守卫 —— 严禁过度改路由。"""
        res = _run_step(
            monkeypatch,
            "推荐一双跑鞋",
            '{"toolName": "searchProducts", "args": {"query": "跑鞋"}}',
            _SHOES_ONLY,
        )
        assert res["toolExecutedName"] == "searchProducts"

    def test_outfit_word_without_clothing_anchor_stays_on_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """只有「搭配」无衣着锚词不劫持(判据 = 搭配形态 × 衣着锚词 双条件)。"""
        res = _run_step(
            monkeypatch,
            "帮我搭配一下购买预算",
            '{"toolName": "searchProducts", "args": {"query": "预算"}}',
            _SHOES_ONLY,
        )
        assert res["toolExecutedName"] == "searchProducts"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
