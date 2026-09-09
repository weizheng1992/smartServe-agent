"""商户 aurora RAG 知识库:文件摄取 → 播种 → 检索全链回归(rag/knowledge_files.py + db/seed.py)。

钉死三件事:
1. 解析器:docs/knowledge Markdown(frontmatter + ## 章节)切成带 docTitle/headerPath 的
   切片,SOP 有序列表原子不拆,缺 businessId 的文件整份跳过(多租户安全);
2. 播种:_seed_rag_documents 读文件注入 aurora 知识,双跑幂等(按 source_url 整组替换),
   并一次性清理 2026-09-09 前内联硬编码的伪 URL 旧行;
3. 检索:ContextualRAG("aurora") 只召回 aurora 切片,竞品知识与平台切片零泄漏。

全程打桩 embedding(seed._embed / get_embedding_model 返回固定向量,检索侧注入
precomputed_embedding),零 LLM/零向量模型。
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from engine_py.rag.knowledge_files import (
    MAX_CHUNK_SIZE,
    default_knowledge_dir,
    load_knowledge_chunks,
    parse_knowledge_file,
)

_EMB = json.dumps([1.0, 0.0])  # 与检索侧 precomputed [1,0] 余弦=1,必过 0.4 断路阀


# ---------------------------------------------------------------------------
# 1. 解析器(纯函数,零 DB)
# ---------------------------------------------------------------------------
def test_parse_aurora_knowledge_file():
    chunks = parse_knowledge_file(default_knowledge_dir() / "aurora_store_and_products.md")
    sections = [c.header_path.split(" > ")[-1] for c in chunks]
    assert sections == [
        "售后退换货政策",
        "尺码与版型指南",
        "户外面料护理与保养",
        "物流配送说明",
        "门店与会员服务",
    ]
    for chunk in chunks:
        assert chunk.business_id == "aurora"
        assert chunk.doc_title == "极光潮品门店与商品知识指南"
        assert chunk.source_url == "aurora_store_and_products.md"
        assert chunk.category == "product_knowledge"
        assert 0 < len(chunk.chunk_text) <= MAX_CHUNK_SIZE
        assert "aurora" in chunk.contextual_summary()
    joined = "\n".join(c.chunk_text for c in chunks)
    # 商户域事实对齐 merchant_seed SPU 数据与 7 天退货基准
    assert "7 天内无理由退换货" in joined
    assert "42码=260mm" in joined


def test_ordered_list_sop_stays_intact(tmp_path):
    doc = tmp_path / "demo_sop.md"
    doc.write_text(
        "---\ntitle: SOP 演示\nbusinessId: demo\ncategory: operation_guide\n---\n\n"
        "# SOP 演示\n\n## 操作步骤\n1. 第一步:打开控制台。\n2. 第二步:点击申请按钮。\n"
        "3. 第三步:确认提交。\n\n## 无归属说明\n",
        encoding="utf-8",
    )
    chunks = parse_knowledge_file(doc)
    sop_chunks = [c for c in chunks if "操作步骤" in c.header_path]
    assert len(sop_chunks) == 1
    for step in ("第一步", "第二步", "第三步"):
        assert step in sop_chunks[0].chunk_text


def test_file_without_business_id_skipped(tmp_path):
    doc = tmp_path / "orphan.md"
    doc.write_text("---\ntitle: 孤儿文档\n---\n\n# 孤儿文档\n\n## 章节\n内容\n", encoding="utf-8")
    assert parse_knowledge_file(doc) == []


# ---------------------------------------------------------------------------
# 2. 播种幂等 + 旧行清理(密封 PG)
# ---------------------------------------------------------------------------
async def _run_seed_twice(factory, monkeypatch) -> None:
    from engine_py.db import seed

    async def _fake_embed(_text: str) -> str:
        return _EMB

    monkeypatch.setattr(seed, "_embed", _fake_embed)
    for _ in range(2):
        async with factory.begin() as conn:
            await seed._seed_rag_documents(conn)


async def _counts(factory) -> dict[str, int]:
    async with factory.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT business_id, COUNT(*) FROM rag_documents "
                    "GROUP BY business_id ORDER BY business_id"
                )
            )
        ).all()
    return {business_id: count for business_id, count in rows}


def test_seed_rag_documents_idempotent_and_replaces_legacy(pg_factory, monkeypatch):
    async def _scenario() -> None:
        # 铺场:空表 + 一条 2026-09-09 前的硬编码伪 URL 旧行 + 管理端人工新增两行
        # (其中一行与知识文件同名但归属异租户 —— 替换删除必须带租户限定,不得误伤)
        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))
            await conn.execute(
                text(
                    "INSERT INTO rag_documents (business_id, source_url, chunk_text) "
                    "VALUES ('nike', 'https://nike.com/policies/refund', 'legacy')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO rag_documents (business_id, source_url, chunk_text) "
                    "VALUES ('aurora', 'manual_ops.md', '人工新增,不得被种子清掉')"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO rag_documents (business_id, source_url, chunk_text) "
                    "VALUES ('nike', 'aurora_store_and_products.md', '同名异租户,不得误伤')"
                )
            )

        await _run_seed_twice(pg_factory, monkeypatch)

        counts = await _counts(pg_factory)
        expected_files: dict[str, int] = {}
        for chunk in load_knowledge_chunks():
            expected_files[chunk.business_id] = expected_files.get(chunk.business_id, 0) + 1
        expected_files["aurora"] += 1  # 人工新增行保留
        expected_files["nike"] += 1  # 同名异租户行保留
        assert counts == expected_files

        async with pg_factory.begin() as conn:
            legacy = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM rag_documents "
                        "WHERE source_url = 'https://nike.com/policies/refund'"
                    )
                )
            ).scalar_one()
            aurora_meta = (
                await conn.execute(
                    text(
                        "SELECT metadata ->> 'docTitle', metadata ->> 'headerPath' "
                        "FROM rag_documents WHERE business_id = 'aurora' AND source_url = "
                        "'aurora_store_and_products.md' LIMIT 1"
                    )
                )
            ).first()
        assert legacy == 0, "内联硬编码时代的伪 URL 行应被一次性清理"
        assert aurora_meta is not None
        assert aurora_meta[0] == "极光潮品门店与商品知识指南"
        assert "售后退换货政策" in aurora_meta[1]

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# 3. 检索租户隔离(aurora 只见 aurora,竞品零泄漏)
# ---------------------------------------------------------------------------
def test_contextual_rag_aurora_retrieval_isolated(pg_factory, monkeypatch):
    async def _scenario() -> None:
        from engine_py.rag import contextual_rag as cr

        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))
        await _run_seed_twice(pg_factory, monkeypatch)

        results = await cr.ContextualRAG("aurora").search_relevant_docs(
            "极光潮品退换货政策尺码", limit=3, precomputed_embedding=[1.0, 0.0]
        )
        assert results, "aurora 知识库应召回至少一条切片"
        assert all(r["businessId"] == "aurora" for r in results)
        joined = "\n".join(r["chunkText"] for r in results)
        assert "极光潮品" in joined
        for competitor in ("Nike", "Adidas", "三里屯", "淮海路"):
            assert competitor not in joined

        nike_results = await cr.ContextualRAG("nike").search_relevant_docs(
            "门店营业时间保养", limit=3, precomputed_embedding=[1.0, 0.0]
        )
        assert nike_results
        assert all(r["businessId"] == "nike" for r in nike_results)
        assert "极光潮品" not in "\n".join(r["chunkText"] for r in nike_results)

    asyncio.run(_scenario())


def test_ensure_seed_data_cold_start_reads_knowledge_files(pg_factory, monkeypatch):
    """空表冷启动:_ensure_seed_data 优先摄取 docs/knowledge(与 seed 同源),aurora 即刻可检索。"""

    async def _scenario() -> None:
        from engine_py.rag import contextual_rag as cr

        class _FakeEmbeddingModel:
            async def aembed_query(self, _text: str) -> list[float]:
                return [1.0, 0.0]

        monkeypatch.setattr(cr, "get_embedding_model", lambda: _FakeEmbeddingModel())

        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))

        results = await cr.ContextualRAG("aurora").search_relevant_docs(
            "极光潮品物流配送", limit=2, precomputed_embedding=[1.0, 0.0]
        )
        assert results
        assert all(r["businessId"] == "aurora" for r in results)

        async with pg_factory.begin() as conn:
            aurora_count = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM rag_documents WHERE business_id = 'aurora'")
                )
            ).scalar_one()
        assert aurora_count == len(
            [c for c in load_knowledge_chunks() if c.business_id == "aurora"]
        )

    asyncio.run(_scenario())


def test_ensure_seed_data_cold_start_skips_without_knowledge_files(pg_factory, monkeypatch):
    """空表冷启动 × 知识文件不可用/目录空:跳过自愈播种,不得以内联写死切片
    (TS 旧文案 SEED_DOCS)兜底 —— 种子与冷启动降级同源,知识只有 docs/knowledge
    一个来源(2026-09-09 评审修复;旧行为降级路径与种子漂移成两套知识)。"""

    async def _scenario() -> None:
        from engine_py.rag import contextual_rag as cr

        monkeypatch.setattr(cr, "load_knowledge_chunks", lambda *args, **kwargs: [])

        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))

        results = await cr.ContextualRAG("ecommerce").search_relevant_docs(
            "退货政策", limit=2, precomputed_embedding=[1.0, 0.0]
        )
        assert results == [], "无知识文件时不得检索出内联兜底切片"

        async with pg_factory.begin() as conn:
            total = (
                await conn.execute(text("SELECT COUNT(*) FROM rag_documents"))
            ).scalar_one()
        assert total == 0, "冷启动降级不得写入内联 SEED_DOCS 行"

    asyncio.run(_scenario())
