"""商品知识 RAG 入库与咨询闸信号(2026-09-13)。

症状:「极光 420g重磅毛圈棉抽绳束脚慢 特点」落咨询直答,RAG 只有店铺政策
没有商品信息,诚实答「没找到」。三件套:①商户真货架派生商品知识切片
(真数据红线:内容全部来自 merchant_spus/skus 真实字段,严禁为虚构商品
编造参数);②自愈播种升级 source 级补齐(新知识文件对已播种库生效);
③咨询闸补商品知识强信号词(「特点/规格/材质」不受 12 字裸话题限制)。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from engine_py.rag.knowledge_files import KnowledgeChunk
from engine_py.rag.product_knowledge import build_product_chunks, sync_product_knowledge
from engine_py.triage.consult_fast_path import is_consult_query

# ── build_product_chunks 纯函数(真实字段形态)──────────────────────────────


def _fake_rows() -> list[dict]:
    return [
        {
            "id": "uuid-1",
            "spu_code": "SPU-010",
            "title": "极光 420g重磅毛圈棉抽绳束脚慢跑裤",
            "subtitle": "420g毛圈棉 | 后防盗拉链袋 | 高弹罗纹收口",
            "description": "极光 420g重磅毛圈棉抽绳束脚慢跑裤 的长文案",
            "category": "下装裤类",
            "specs": {"面料材质": "420g 重磅毛圈棉混纺", "版型": "宽松锥形 Easy Fit"},
            "status": "ON_SALE",
            "skus": [
                {"sku_title": "重磅束脚慢跑裤 炭黑 M码", "price": 349.0, "stock": 110, "spec_attributes": {"尺码": "M"}},
                {"sku_title": "重磅束脚慢跑裤 浅麻灰 L码", "price": 349.0, "stock": 70, "spec_attributes": {"尺码": "L"}},
            ],
        }
    ]


class TestBuildProductChunks:
    def test_chunk_carries_real_specs_and_prices(self):
        chunks = build_product_chunks(_fake_rows(), "ecommerce")
        assert len(chunks) == 1
        c = chunks[0]
        body = c.chunk_text
        assert "420g 重磅毛圈棉混纺" in body, "核心规格必须来自真实 specs"
        assert "宽松锥形 Easy Fit" in body
        assert "炭黑 M码 ¥349.0" in body, "在售规格与价格必须来自真实 SKU"
        assert "库存状态" in body
        assert c.source_url == "product_catalog_sync.md"
        assert c.category == "product_knowledge"
        assert c.header_path.startswith("商品目录 > 下装裤类 >")

    def test_no_fabricated_content_for_bare_spu(self):
        """无 subtitle/specs/SKU 的 SPU:切片不得编造内容。"""
        bare = [{"id": "u", "spu_code": "S", "title": "某商品", "subtitle": None,
                 "description": None, "category": None, "specs": None, "status": "ON_SALE", "skus": []}]
        chunks = build_product_chunks(bare, "ecommerce")
        assert chunks[0].chunk_text == "某商品", "无真实字段时正文只有标题"

    def test_embedding_input_contains_context_prefix(self):
        c = build_product_chunks(_fake_rows(), "ecommerce")[0]
        assert c.embedding_input().startswith("[Context]"), "对齐 knowledge_files 上下文前缀契约"


# ── sync_product_knowledge 密封集成 ───────────────────────────────────────


_MERCHANT_DDL = [
    """
    CREATE TABLE IF NOT EXISTS merchant_spus (
      id UUID PRIMARY KEY,
      spu_code TEXT NOT NULL UNIQUE,
      title TEXT NOT NULL,
      subtitle TEXT,
      description TEXT,
      category TEXT NOT NULL DEFAULT '下装裤类',
      specs JSONB DEFAULT '{}'::jsonb,
      status TEXT NOT NULL DEFAULT 'ON_SALE',
      created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS merchant_skus (
      id UUID PRIMARY KEY,
      spu_id UUID NOT NULL,
      sku_code TEXT NOT NULL UNIQUE,
      sku_title TEXT,
      price NUMERIC(10,2) NOT NULL,
      stock INTEGER NOT NULL DEFAULT 0,
      spec_attributes JSONB DEFAULT '{}'::jsonb
    )
    """,
]

import json as _json
import uuid as _uuid


async def _seed_merchant(engine, title: str = "极光 420g重磅毛圈棉抽绳束脚慢跑裤"):
        async with engine.begin() as conn:
            for ddl in _MERCHANT_DDL:
                await conn.execute(text(ddl))
            await conn.execute(text("TRUNCATE merchant_skus, merchant_spus"))
            sid = _uuid.uuid5(_uuid.NAMESPACE_URL, "SPU-010")
            await conn.execute(
                text(
                    "INSERT INTO merchant_spus (id, spu_code, title, subtitle, description, category, specs) "
                    "VALUES (CAST(:id AS uuid), 'SPU-010', :t, :st, :d, '下装裤类', CAST(:spec AS jsonb))"
                ).bindparams(
                    id=str(sid), t=title, st="420g毛圈棉 | 高弹罗纹收口", d=None,
                    spec=_json.dumps({"面料材质": "420g 重磅毛圈棉混纺"}, ensure_ascii=False),
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, price, stock, spec_attributes) "
                    "VALUES (CAST(:id AS uuid), CAST(:sid AS uuid), 'AURORA-SKU-010-BLK-M', "
                    "'重磅束脚慢跑裤 炭黑 M码', 349.0, 110, CAST(:attr AS jsonb))"
                ).bindparams(id=str(_uuid.uuid5(_uuid.NAMESPACE_URL, "sku1")), sid=str(sid),
                             attr=_json.dumps({"尺码": "M"}, ensure_ascii=False))
            )


class TestSyncProductKnowledge:
    def test_sync_writes_and_replaces_idempotently(self, pg_factory, monkeypatch):
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from engine_py.tools_registry import order_domain

        engine = pg_factory.kw["bind"]
        url = engine.url.render_as_string(hide_password=False)
        merchant_engine = create_async_engine(url, poolclass=NullPool)
        original = order_domain._merchant_reader_engine

        class _FakeEmbed:
            async def aembed_query(self, text_val: str) -> list[float]:
                return [0.1, 0.2, 0.3]

        monkeypatch.setattr(
            "engine_py.rag.product_knowledge.get_embedding_model", lambda: _FakeEmbed()
        )
        order_domain._merchant_reader_engine = lambda: merchant_engine

        async def scenario():
            await _seed_merchant(engine)
            first = await sync_product_knowledge("ecommerce")
            assert first == {"synced": 1}
            async with engine.connect() as conn:
                rows = (await conn.execute(
                    text("SELECT chunk_text FROM rag_documents WHERE source_url='product_catalog_sync.md'")
                )).scalars().all()
            assert len(rows) == 1
            assert "420g 重磅毛圈棉混纺" in rows[0]

            # 幂等:重跑不翻倍
            second = await sync_product_knowledge("ecommerce")
            assert second == {"synced": 1}
            async with engine.connect() as conn:
                n = (await conn.execute(
                    text("SELECT COUNT(*) FROM rag_documents WHERE source_url='product_catalog_sync.md'")
                )).scalar()
            assert n == 1

            # 商户改标题 → 重跑 → 切片更新(重启生效契约)
            await _seed_merchant(engine, title="极光 420g重磅毛圈棉抽绳束脚慢跑裤 2026款")
            third = await sync_product_knowledge("ecommerce")
            assert third == {"synced": 1}
            async with engine.connect() as conn:
                headers = (await conn.execute(
                    text("SELECT metadata->>'headerPath' FROM rag_documents WHERE source_url='product_catalog_sync.md'")
                )).scalars().all()
            assert any("2026款" in h for h in headers), "标题变更必须反映到 headerPath(重启生效契约)"
            assert len(headers) == 1

        try:
            asyncio.run(scenario())
        finally:
            order_domain._merchant_reader_engine = original
            asyncio.run(merchant_engine.dispose())

    def test_sync_honest_skip_on_unreachable_merchant(self, pg_factory, monkeypatch):
        from engine_py.tools_registry import order_domain

        def _boom():
            raise RuntimeError("merchant down")

        original = order_domain._merchant_reader_engine
        order_domain._merchant_reader_engine = _boom
        try:
            result = asyncio.run(sync_product_knowledge("ecommerce"))
        finally:
            order_domain._merchant_reader_engine = original
        assert result.get("skipped") is True and result.get("synced") == 0


# ── 自愈播种 source 级补齐 ────────────────────────────────────────────────


class TestSelfHealingSourceTopUp:
    def test_new_knowledge_file_ingested_for_seeded_db(self, pg_factory, monkeypatch):
        """已播种库(有其它 source 行)遇到新知识文件:必须补灌 —— 商品知识
        文档对既有库可见的前提。"""
        from engine_py.rag import knowledge_files
        from engine_py.rag.contextual_rag import ContextualRAG

        engine = pg_factory.kw["bind"]
        original_load = knowledge_files.load_knowledge_chunks

        def _two_files():
            return [
                KnowledgeChunk(
                    business_id="ecommerce", source_url="existing.md", doc_title="旧文档",
                    header_path="旧文档 > 政策", chunk_text="政策内容", category="policy",
                ),
                KnowledgeChunk(
                    business_id="ecommerce", source_url="new_product_knowledge.md",
                    doc_title="商品知识", header_path="商品知识 > 洗护",
                    chunk_text="毛圈棉洗护要点", category="product_knowledge",
                ),
            ]

        monkeypatch.setattr("engine_py.rag.contextual_rag.load_knowledge_chunks", _two_files)

        class _FakeEmbed:
            async def aembed_query(self, text_val: str) -> list[float]:
                return [0.5, 0.5]

        monkeypatch.setattr(
            "engine_py.rag.contextual_rag.get_embedding_model", lambda: _FakeEmbed()
        )

        async def scenario():
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM rag_documents"))
                await conn.execute(
                    text(
                        "INSERT INTO rag_documents (business_id, source_url, chunk_text, "
                        "contextual_summary, embedding, metadata) VALUES "
                        "('ecommerce', 'existing.md', '政策内容', 'summary', '[0.1,0.1]', '{}')"
                    )
                )
            rag = ContextualRAG("ecommerce")
            await rag._ensure_seed_data()
            async with engine.connect() as conn:
                sources = (await conn.execute(
                    text("SELECT DISTINCT source_url FROM rag_documents ORDER BY source_url")
                )).scalars().all()
            return sources

        sources = asyncio.run(scenario())
        assert "new_product_knowledge.md" in sources, "新知识文件必须被 source 级补齐"

    def test_content_change_reingests_same_source(self, pg_factory, monkeypatch):
        """文件内容修订 → 同 source 整组重灌(知识文档修订免手动清库)。"""
        from engine_py.rag.contextual_rag import ContextualRAG

        engine = pg_factory.kw["bind"]
        holder: dict = {"body": "旧版内容"}

        def _one_file():
            return [
                KnowledgeChunk(
                    business_id="ecommerce", source_url="rev.md", doc_title="d",
                    header_path="d > h", chunk_text=holder["body"], category="policy",
                )
            ]

        monkeypatch.setattr("engine_py.rag.contextual_rag.load_knowledge_chunks", _one_file)

        class _FakeEmbed:
            async def aembed_query(self, text_val: str) -> list[float]:
                return [0.5, 0.5]

        monkeypatch.setattr(
            "engine_py.rag.contextual_rag.get_embedding_model", lambda: _FakeEmbed()
        )

        async def scenario():
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM rag_documents"))
            rag = ContextualRAG("ecommerce")
            await rag._ensure_seed_data()
            holder["body"] = "新版修订内容"
            await rag._ensure_seed_data()
            async with engine.connect() as conn:
                texts = (await conn.execute(
                    text("SELECT chunk_text FROM rag_documents WHERE source_url='rev.md'")
                )).scalars().all()
            return texts

        texts = asyncio.run(scenario())
        assert texts == ["新版修订内容"], "内容修订必须整组重灌"

    def test_idempotent_no_duplication(self, pg_factory, monkeypatch):
        from engine_py.rag.contextual_rag import ContextualRAG

        engine = pg_factory.kw["bind"]

        def _one_file():
            return [
                KnowledgeChunk(
                    business_id="ecommerce", source_url="only.md", doc_title="d",
                    header_path="d > h", chunk_text="内容", category="policy",
                )
            ]

        monkeypatch.setattr("engine_py.rag.contextual_rag.load_knowledge_chunks", _one_file)

        class _FakeEmbed:
            async def aembed_query(self, text_val: str) -> list[float]:
                return [0.5, 0.5]

        monkeypatch.setattr(
            "engine_py.rag.contextual_rag.get_embedding_model", lambda: _FakeEmbed()
        )

        async def scenario():
            async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM rag_documents"))
            rag = ContextualRAG("ecommerce")
            await rag._ensure_seed_data()
            await rag._ensure_seed_data()
            async with engine.connect() as conn:
                return (await conn.execute(
                    text("SELECT COUNT(*) FROM rag_documents WHERE source_url='only.md'")
                )).scalar()

        assert asyncio.run(scenario()) == 1


# ── 咨询闸商品知识信号 ───────────────────────────────────────────────────


class TestConsultGateKnowledgeSignal:
    def test_product_feature_questions_are_consult(self):
        assert is_consult_query("极光 420g重磅毛圈棉抽绳束脚慢 特点")
        assert is_consult_query("冲锋衣的材质是什么")
        assert is_consult_query("这个背包规格有哪些")

    def test_non_knowledge_inputs_unchanged(self):
        assert not is_consult_query("今天天气怎么样")
        assert not is_consult_query("推荐几款跑步鞋")
        assert not is_consult_query("查一下我的订单")
        assert is_consult_query("退货政策是什么"), "既有政策问句不回归"


if __name__ == "__main__":
    pytest.main([__file__])
