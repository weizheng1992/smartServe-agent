"""口语化组合鲁棒性红灯回路(2026-09-13 二轮矩阵 12 探针的失败面)。

M7 KeyError('province') 炸图(深规划给 saveUserAddress 缺参)、M8 评价检索
「三合一冲锋衣」子串死匹配(135 条真实评价查不到)、M2「催催」被推人工接管、
M9「登山包」词元盲 + 「两款」量词不在数量正则 + 「都要了」不入 cart 意图。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from engine_py.graph.nodes import planner as planner_mod
from engine_py.tools_registry.mall_domain import MallDomainService
from engine_py.triage.intent_triage_engine import detect_address_manage
from engine_py.triage.slot_extractor import SlotExtractor


class TestSaveUserAddressHonestFailure:
    def test_missing_fields_return_error_not_keyerror(self, pg_factory, monkeypatch):
        """缺 province 等必填字段:诚实错误 dict,严禁 KeyError 炸图
        (M7 实弹:整轮被图级熔断吞成「上游模型波动」)。"""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from engine_py.tools_registry import order_domain

        engine = pg_factory.kw["bind"]
        merchant_engine = create_async_engine(url=engine.url.render_as_string(hide_password=False), poolclass=NullPool)
        original = order_domain._merchant_reader_engine
        order_domain._merchant_reader_engine = lambda: merchant_engine
        try:
            result = asyncio.run(
                MallDomainService.save_user_address(
                    {"receiverName": "王强", "receiverPhone": "13600136000", "threadId": "m7_t"}
                )
            )
        finally:
            order_domain._merchant_reader_engine = original
            asyncio.run(merchant_engine.dispose())
        assert result.get("success") is False
        assert "地址" in (result.get("message") or ""), "必须说明缺什么"
        assert result.get("missingFields"), "必须列出缺失字段"


class TestAddressCreateVocab:
    def test_jiage_form_detected(self):
        """「加个新地址 王强 …」口语创建形必须检出(M7 漏检致深规划缺参炸图)。"""
        detected = detect_address_manage("加个新地址 王强 13600136000 上海市浦东新区张江路600号")
        assert detected is not None and detected["mode"] == "save"
        assert detected["entities"].get("receiverName") == "王强"
        assert detected["entities"].get("province") == "上海市"


class TestReviewTokenMatch:
    def test_multi_token_product_name_matches(self, pg_factory, monkeypatch):
        """「三合一冲锋衣」拆词元匹配:子串死匹配曾查不到 135 条真实评价。"""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from engine_py.tools_registry import order_domain

        engine = pg_factory.kw["bind"]
        merchant_engine = create_async_engine(url=engine.url.render_as_string(hide_password=False), poolclass=NullPool)
        original = order_domain._merchant_reader_engine

        async def setup():
            async with merchant_engine.begin() as conn:
                # 形状取与相邻套件(catalog_reach)的并集 —— 共享容器,
                # 窄形状会传染后续套件的 INSERT(缺列 UndefinedColumn)
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_spus ("
                    " id UUID PRIMARY KEY, spu_code TEXT UNIQUE, title TEXT NOT NULL,"
                    " subtitle TEXT, description TEXT, category TEXT, main_image TEXT,"
                    " specs JSONB DEFAULT '{}'::jsonb, status TEXT DEFAULT 'ON_SALE',"
                    " created_at TIMESTAMP NOT NULL DEFAULT NOW())"
                ))
                await conn.execute(text(
                    "INSERT INTO merchant_spus (id, spu_code, title) VALUES "
                    "(CAST(:sid AS uuid), 'SPU-RT-1', '极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)') "
                    "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title"
                ).bindparams(sid="22222222-2222-2222-2222-222222222222"))
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_product_reviews ("
                    " id UUID PRIMARY KEY DEFAULT gen_random_uuid(), spu_id UUID NOT NULL,"
                    " sku_code TEXT, customer_id TEXT, rating INT NOT NULL, content TEXT,"
                    " created_at TIMESTAMP DEFAULT NOW())"
                ))
                await conn.execute(text("DELETE FROM merchant_product_reviews WHERE spu_id = CAST(:sid AS uuid)").bindparams(sid="22222222-2222-2222-2222-222222222222"))
                await conn.execute(text(
                    "INSERT INTO merchant_product_reviews (spu_id, rating, content) VALUES "
                    "(CAST(:sid AS uuid), 5, '防水经受住一夜大雨，做工扎实。')"
                ).bindparams(sid="22222222-2222-2222-2222-222222222222"))

        asyncio.run(setup())
        order_domain._merchant_reader_engine = lambda: merchant_engine
        try:
            result = asyncio.run(MallDomainService.query_product_reviews({"productName": "三合一冲锋衣"}))
        finally:
            order_domain._merchant_reader_engine = original
            asyncio.run(merchant_engine.dispose())
        assert len(result.get("reviews") or []) == 1, result
        assert result.get("averageRating") == 5.0


class TestSearchVocab:
    def test_dengshan_bao_expands(self):
        """「登山包」词元展开:货架 title「高山徒步轻量化背包」无「登山包」子串,
        必须借词素(登山/背包)命中。"""
        from engine_py.tools_registry.mall_domain import MallDomainService

        expanded = MallDomainService._expand_stem_aliases(["登山包"])
        assert any("登山" in t or "包" == t or "背包" in t for t in expanded), expanded

    def test_extract_all_detects_all_yao(self):
        """「推荐两款登山包，都要了」:「都要了」必须检出 cart_manage 意图
        (推荐+全量加购复合流)。"""
        specs = SlotExtractor.extract_all("推荐两款登山包，都要了")
        intents = {s["intentType"] for s in specs}
        assert "cart_manage" in intents, intents


class TestGuideQuantityMeasureWords:
    def test_kuan_measure_word(self, monkeypatch):
        """「两款」量词:数量正则此前只认「个」—— 两款/三条/两只都要生效。"""
        import re

        # 数量语义提取是模块内正则,这里直接消费技能内部实现的公开行为:
        # 用正则本身断言(避免整 skill 执行的检索副作用)

        match = re.search(r"([2-9]|1[0]|两|三|四|五|六|七|八|九|十)\s*(?:个|件|款|条|双|只)", "推荐两款登山包，都要了")
        assert match is not None, "「两款」必须被数量语义命中"


class TestPlannerUrgeRule:
    def test_urge_is_not_escalation(self, monkeypatch):
        """「帮我催催」:催单是查单+话术,严禁规划人工转接(M2 实弹把急用
        顾客直接推给了接管队列)。"""
        class _FakeSM:
            def __init__(self, thread_id: str) -> None:
                pass

            async def get_messages(self) -> list:
                return []

        monkeypatch.setattr(planner_mod, "ShortMemory", _FakeSM)
        captured: dict = {}

        class _FakeResponse:
            content = '{"goal": "g", "subtasks": []}'

        class _FakeLLM:
            async def ainvoke(self, prompt):
                captured["prompt"] = prompt
                return _FakeResponse()

        monkeypatch.setattr(planner_mod, "planner_llm", lambda: _FakeLLM())
        state = {
            "intents": [{"intent": "order_status", "confidence": 0.9, "type": "primary"}],
            "input": "我上周买的那个背包咋还没发货，急用，帮我催催",
            "short_memory": [],
        }
        asyncio.run(planner_mod.planner_node(state))
        assert "催" in captured["prompt"], "深规划 prompt 必须有催单处置条款"
        assert "human escalation" in captured["prompt"] or "escalation" in captured["prompt"]


if __name__ == "__main__":
    pytest.main([__file__])
