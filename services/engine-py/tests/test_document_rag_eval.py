"""文档 RAG 检索评测基线:合成 PRD 语料 → 摄取 → 12 问 hit@k 钉死。

与 promptfoo rag 套件(eval/promptfoo.rag.yaml,直评 search_relevant_docs)同一
评测取向,但语料换成文档摄取管线:python-docx 现场合成三份 PRD(会员积分 /
退换货政策 / 物流时效)+ 一份竞对租户文档,经 ingest_document_file 真实切块入库,
问答断言期望文档进 top-2、表格类问题召回含 table 切片、跨租户零泄漏。

诚实边界:embedding 是确定性词面桩(token 指示向量,与 test_document_rag 同桩),
本基线钉的是**管线接通与排序**(切块 → 摘要模板 → 混合检索 → 元数据),不是
bge 语义检索质量 —— 后者由真弹冒烟(真实 bge + 真实样例文档)覆盖。桩下混合分
绝对值低于真实 bge,故评测调用显式 min_score=0.1(阈值闸行为本身已由
test_min_score_gate_honest_empty 单独钉死),生产检索仍走默认 0.4。
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from test_document_rag import _ingest_docx, _StubEmbeddings  # 同桩同摄取助手,单一实现

# 语料:三份文档 × (文档名, 结构块)
_CORPUS_AURORA = {
    "会员积分规则.docx": [
        ("h1", "极光会员积分规则"),
        ("p", "会员消费一元累计一分,积分年度末清零。"),
        ("h2", "积分兑换门槛"),
        ("p", "积分可在商城兑换优惠券与实物礼品。"),
        ("table", [["兑换项目", "所需积分"], ["10 元优惠券", "1000"], ["帆布袋", "2000"], ["保温杯", "5000"]]),
        ("h2", "等级与权益"),
        ("p", "会员等级按年度累计消费自动升降级,权益随等级变化。"),
    ],
    "退换货政策.docx": [
        ("h1", "极光退换货政策"),
        ("h2", "退货时效"),
        ("p", "签收后 7 天内无理由退货,吊牌完好为前提。"),
        ("h2", "退款时效"),
        ("p", "退货入库后 3 个工作日内原路退款。"),
        ("h2", "不予退换情形"),
        ("table", [["情形", "说明"], ["贴身衣物", "卫生考量不支持退换"], ["定制品", "定制刻字商品不支持退换"]]),
    ],
    "物流配送时效.docx": [
        ("h1", "极光物流配送说明"),
        ("h2", "发货时效"),
        ("p", "现货商品 48 小时内发货,预售商品按页面标注时间发货。"),
        ("h2", "运费标准"),
        ("p", "单笔订单满 99 元包邮,不满收取 8 元运费;偏远地区另计。"),
    ],
}

_CORPUS_NIKE = {
    "nike会员条款.docx": [
        ("h1", "Nike 会员条款"),
        ("h2", "黑卡权益"),
        ("p", "Nike 黑卡会员享生日双倍积分与专属客服通道。"),
    ],
}

# 评测集:(问题, 期望 source_url, 期望 headerPath 片段或 None)
_EVAL_CASES = [
    ("积分怎么兑换 优惠券 门槛", "会员积分规则.docx", None),
    ("保温杯 兑换 需要多少积分", "会员积分规则.docx", None),
    ("积分年度清零 规则", "会员积分规则.docx", None),
    ("退货 时效 吊牌 无理由", "退换货政策.docx", None),
    ("退款 几个工作日 原路退回", "退换货政策.docx", None),
    ("哪些情况 不支持退换 定制品", "退换货政策.docx", None),
    ("什么时候发货 48 小时 现货", "物流配送时效.docx", None),
    ("运费 包邮标准 多少钱", "物流配送时效.docx", None),
    ("偏远地区 运费 另计吗", "物流配送时效.docx", None),
    ("会员 等级 权益 积分 累计", "会员积分规则.docx", None),
    ("退货 入库 退款 流程", "退换货政策.docx", None),
    ("预售商品 发货时间", "物流配送时效.docx", None),
]


def _query_vec(question: str) -> list[float]:
    return _StubEmbeddings()._vec(question)


def test_document_rag_hit_at_k_baseline(pg_factory, monkeypatch, tmp_path):
    """12 问全部 hit@2:期望文档出现在 top-2 召回内。改动切块/检索管线导致
    本基线翻红时,必须给出质量变化的明确理由,禁止无脑调阈值刷绿。"""

    async def _scenario() -> None:
        from engine_py.rag import contextual_rag as cr

        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))

        for name, blocks in _CORPUS_AURORA.items():
            result = await _ingest_docx(pg_factory, monkeypatch, tmp_path, name, blocks, "aurora")
            assert result.status == "ingested", f"{name} 摄取失败: {result.reason}"
        for name, blocks in _CORPUS_NIKE.items():
            await _ingest_docx(pg_factory, monkeypatch, tmp_path, name, blocks, "nike")

        misses: list[str] = []
        for question, expected_source, _expected_header in _EVAL_CASES:
            hits = await cr.ContextualRAG("aurora").search_relevant_docs(
                question, limit=2, precomputed_embedding=_query_vec(question), min_score=0.1
            )
            sources = [h["sourceUrl"] for h in hits]
            if expected_source not in sources:
                misses.append(f"{question!r} → top2={sources}(期望 {expected_source})")
        assert not misses, "hit@2 基线翻红:\n" + "\n".join(misses)

    asyncio.run(_scenario())


def test_document_rag_table_chunk_recall(pg_factory, monkeypatch, tmp_path):
    """表格类问题必须能召回 contentType=table 切片(表格原子块的可检索性)。"""

    async def _scenario() -> None:
        from engine_py.rag import contextual_rag as cr

        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))
        for name, blocks in _CORPUS_AURORA.items():
            await _ingest_docx(pg_factory, monkeypatch, tmp_path, name, blocks, "aurora")

        hits = await cr.ContextualRAG("aurora").search_relevant_docs(
            "保温杯 兑换 所需积分", limit=5, precomputed_embedding=_query_vec("保温杯 兑换 所需积分"), min_score=0.1
        )
        assert hits
        assert any(
            (h.get("parentChunk") is None) and h["chunkText"].lstrip().startswith("|") for h in hits
        ), f"表格类问题应召回管道表切片,实得: {[h['chunkText'][:40] for h in hits]}"
        assert any("保温杯" in h["chunkText"] for h in hits), "表格单元格内容必须原样可检"

    asyncio.run(_scenario())


def test_document_rag_cross_tenant_zero_leak(pg_factory, monkeypatch, tmp_path):
    """竞对租户文档对 aurora 检索零泄漏(文档摄取源不豁免租户不变量 #1)。"""

    async def _scenario() -> None:
        from engine_py.rag import contextual_rag as cr

        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))
        for name, blocks in {**_CORPUS_AURORA, **_CORPUS_NIKE}.items():
            tenant = "nike" if name.startswith("nike") else "aurora"
            await _ingest_docx(pg_factory, monkeypatch, tmp_path, name, blocks, tenant)

        nike_question = "黑卡 生日 双倍积分 专属客服"
        nike_hits = await cr.ContextualRAG("nike").search_relevant_docs(
            nike_question, limit=3, precomputed_embedding=_query_vec(nike_question), min_score=0.1
        )
        assert nike_hits
        assert all(h["businessId"] == "nike" for h in nike_hits)

        aurora_hits = await cr.ContextualRAG("aurora").search_relevant_docs(
            nike_question, limit=5, precomputed_embedding=_query_vec(nike_question), min_score=0.1
        )
        assert all(h["businessId"] == "aurora" for h in aurora_hits), "跨租户泄漏"
        assert all("Nike" not in h["chunkText"] for h in aurora_hits)

    asyncio.run(_scenario())
