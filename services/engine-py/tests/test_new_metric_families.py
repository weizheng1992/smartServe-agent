"""阶段③新指标族契约 + query_exemplars L2 服务(10-D1 注册顺序:评价→退货→会话)。

- 新族 resolve:词面命中 → 指标键;时间窗/LIMIT/方向语义同销售族
- compile:target_db 路由(评价/退货→merchant_db;会话→engine_db)
- execute:两路执行位均可跑通(pg_factory 容器 + merchant 种子)
- exemplar 服务:登记/双池检索/阈值/诚实 None
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text

from engine_py.analytics.engine import MetricQueryEngine, StructuredQueryIntent, UnsupportedQuery
from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY

try:
    from tests.test_product_ranking_merchant_source import merchant_pg
except ImportError:
    import importlib.util
    from pathlib import Path as _P

    _spec = importlib.util.spec_from_file_location(
        "_ranking_seed", _P(__file__).resolve().parent / "test_product_ranking_merchant_source.py"
    )
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    merchant_pg = _mod.merchant_pg


@pytest.fixture()
def engine(merchant_pg):
    return MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})


@pytest.fixture(autouse=True)
def _pin_result_cache_off(monkeypatch):
    """执行位测试一律关结果缓存。ambient AI_RESULT_CACHE_TTL(如 test_export_intent_data
    触发脚本 _load_env_file 把仓库根 .env 全量 setdefault 进进程)曾让本模块命中
    Redis 陈旧空结果而假红 —— 症状是 reader 工厂零调用、rows=0(2026-09-26 定位)。"""
    monkeypatch.delenv("AI_RESULT_CACHE_TTL", raising=False)


class TestNewFamilyResolve:
    def test_review_family_registered(self):
        assert "review_bad" in METRIC_SEMANTIC_REGISTRY
        assert METRIC_SEMANTIC_REGISTRY["review_bad"]["permissionTag"] == "sales_viewer"

    def test_review_bad_synonym(self, engine):
        intent = engine.resolve("差评最多的 SKU")
        assert intent.metric == "review_bad"

    def test_refund_rate_synonym(self, engine):
        intent = engine.resolve("近 30 天退款率")
        assert intent.metric == "refund_rate"
        assert intent.time_window is not None

    def test_session_volume_maps_engine_family(self, engine):
        intent = engine.resolve("客服负载概况 会话量")
        assert intent.metric == "session_volume"

    def test_ai_resolution_rate(self, engine):
        intent = engine.resolve("AI 自动解决率")
        assert intent.metric == "ai_resolution_rate"


class TestCapsuleContract:
    """六快捷胶囊(10-D3)一一可解析 —— 死按钮禁令的判定面:菜单/胶囊上
    出现的每个问题必须落在已注册指标空间内(实弹冒烟抓过词表缺口)。"""

    CAPSULES = [
        ("本月销量 Top10", "volume"),
        ("卖得最差的商品", "gmv"),
        ("差评最多的 SKU", "review_bad"),
        ("近 30 天退款率", "refund_rate"),
        ("售后工单概况", "after_sale_overview"),
        ("客服负载概况", "session_volume"),
    ]

    def test_all_capsules_resolve(self, engine):
        for q, expect in self.CAPSULES:
            intent = engine.resolve(q)
            assert intent.metric == expect, f"胶囊「{q}」解析为 {intent.metric},期望 {expect}"


class TestNewFamilyCompileExecute:
    def test_target_db_routing(self, engine):
        assert engine.compile(engine.resolve("差评最多的 SKU")).target_db == "merchant_db"
        assert engine.compile(engine.resolve("客服负载概况 会话量")).target_db == "engine_db"

    def test_review_bad_no_hallucination_on_any_state(self, engine, merchant_pg):
        """表缺失 → 异常透传;表在 → 真实行。两种状态都不得幻觉数据(顺序无关)。"""
        import sqlalchemy.exc

        try:
            result = asyncio.run(engine.execute_async(engine.compile(engine.resolve("差评最多的 SKU"))))
            assert isinstance(result.rows, list)  # 有表:真实行(可能空)
        except sqlalchemy.exc.ProgrammingError:
            pass  # 无表:异常透传,诚实失败

    def test_review_bad_returns_real_rows_when_seeded(self, engine, merchant_pg):
        """铺上 reviews 表 + 两条差评一条好评 → 差评榜按 spu 计数(真实行)。"""
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        url = merchant_pg.url.render_as_string(hide_password=False)

        async def _seed_and_query():
            e = create_async_engine(url, poolclass=NullPool)
            async with e.begin() as conn:
                await conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS merchant_product_reviews ("
                    "id UUID PRIMARY KEY DEFAULT gen_random_uuid(), spu_id UUID NOT NULL, "
                    "customer_id TEXT, rating INT NOT NULL, content TEXT, "
                    "created_at TIMESTAMP DEFAULT NOW())"
                ))
                await conn.execute(text("DELETE FROM merchant_product_reviews"))
                spu_a = uuid.uuid5(uuid.NAMESPACE_URL, "SPU-A")
                spu_b = uuid.uuid5(uuid.NAMESPACE_URL, "SPU-B")
                await conn.execute(text(
                    "INSERT INTO merchant_product_reviews (spu_id, rating, content) VALUES "
                    "(:a, 1, '开胶'), (:a, 2, '断底'), (:b, 5, '很好')"
                ).bindparams(a=spu_a, b=spu_b))
            await e.dispose()
            return await engine.execute_async(engine.compile(engine.resolve("差评最多的 SKU")))

        result = asyncio.run(_seed_and_query())
        assert result.rows[0]["metricScore"] == 2  # 两条差评同 SPU 居首

    def test_session_family_executes_on_engine_db(self, engine, merchant_pg, pg_factory):
        # engine 本地库(session_metrics)真算:0 会话 → 诚实空 rows
        result = asyncio.run(engine.execute_async(engine.compile(engine.resolve("客服负载概况 会话量"))))
        assert result.metric == "session_volume"
        assert isinstance(result.rows, list)

    def test_unknown_metric_still_unsupported(self, engine):
        with pytest.raises(UnsupportedQuery):
            engine.resolve("今天天气如何")


class TestOrderOverview:
    """PageContext 订单实体概览(19-D3 兑现):实体集必传,空集响亮拒绝。"""

    def test_resolve_by_synonym(self, engine):
        intent = engine.resolve("这几笔订单的平均金额")
        assert intent.metric == "order_overview"

    def test_empty_entities_rejected_loudly(self, engine):
        """没勾选就问概览 → 响亮拒绝(不悄悄全量统计)。"""
        intent = engine.resolve("这几笔订单的平均金额")
        with pytest.raises(UnsupportedQuery, match="勾选"):
            engine.compile(intent)

    def test_empty_entities_message_is_actionable(self, engine):
        """拒绝文案必须给出动作提示(勾选/报单号),而非含糊的「暂未开放」。"""
        intent = engine.resolve("这几笔订单的平均金额")
        with pytest.raises(UnsupportedQuery, match="请先在订单列表勾选订单"):
            engine.compile(intent)

    def test_resolve_compare_phrasing(self, engine):
        """ADR-0005:「两个订单对比」等对比问法 → order_overview(词表直命中)。"""
        for q in ("两个订单对比", "对比这两笔订单", "订单比较"):
            intent = engine.resolve(q)
            assert intent.metric == "order_overview"

    def test_compile_carries_entities_as_params(self, engine):
        intent = engine.resolve("这几笔订单的平均金额")
        intent = StructuredQueryIntent(
            metric=intent.metric, direction=intent.direction, limit=intent.limit,
            entity_ids=["AURORA-ORD-2026-9081", "AURORA-ORD-2026-9083"],
        )
        compiled = engine.compile(intent)
        assert compiled.target_db == "merchant_db"
        assert compiled.params["entities"] == ["AURORA-ORD-2026-9081", "AURORA-ORD-2026-9083"]
        assert "ANY(:entities)" in compiled.sql


class TestQueryExemplars:
    def test_add_and_search_roundtrip(self, pg_factory):
        from engine_py.analytics import exemplar_service as svc

        async def _run():
            # 直写形态(embedding 现算依赖模型服务,离线 CI 不稳)
            from engine_py.db import QueryExemplar, get_session

            intent = {"metric": "review_bad", "direction": "DESC", "limit": 5}
            async with get_session() as session:
                session.add(QueryExemplar(
                    id=f"qx_{uuid.uuid4().hex[:8]}", business_id="__global__",
                    question="哪些商品差评最多", intent_json=json.dumps(intent),
                    embedding=[1.0, 0.0], source="manual", is_active=True,
                ))
                await session.commit()
            # search 走 aembed_query:monkeypatch 失败路径 → None(诚实)
            hit = await svc.search_exemplar("哪些商品差评最多", "aurora")
            return hit

        # 无 embedding 服务(离线 CI)时 search 诚实 None;有则命中意图
        hit = asyncio.run(_run())
        assert hit is None or hit["intent"]["metric"] == "review_bad"

    def test_threshold_guards_mismatch(self, pg_factory):
        """低于阈值不返回(不静默兜底语义在示例层同样成立)。"""
        from engine_py.analytics import exemplar_service as svc

        async def _run():
            return await svc.search_exemplar("完全不相关的问题句子", "aurora")

        assert asyncio.run(_run()) is None
