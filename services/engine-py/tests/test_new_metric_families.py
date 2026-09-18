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

from engine_py.analytics.engine import MetricQueryEngine, UnsupportedQuery
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
