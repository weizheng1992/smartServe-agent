"""文档 RAG 单元与摄取回归:切块纪律 / docx 真解析 / 覆盖重建 / 租户隔离。

三层钉死(2026-10-17 文档 RAG):
1. 切块器(document_chunker,纯函数):表格原子块(超长按行组切且表头重复)、
   图片独立块携 imageUrl、首标题前前置段落不丢、有序列表原子沿用 knowledge_files;
2. 解析器(document_parse,真 docling docx 规则后端,零模型下载):标题层级、
   管道表格、插图落盘并改写为 /api/uploads/rag URL;
3. 摄取(document_ingest,密封 PG):同名文件整组替换(覆盖重建,不堆行)、
   metadata 增量键(contentType/sourceFormat/imageUrl)、租户隔离检索。

PDF 路径(docling 版面模型)不进密封套件 —— 权重下载不可接受,由真弹冒烟
(样例 PDF 批量导入 + 检索验证)覆盖;.doc 诚实拒绝在此钉死。

embeddings 全程打桩(token 指示向量的确定性词面桩),零向量模型。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from docx_fixtures import build_docx
from sqlalchemy import text

from engine_py.rag.document_chunker import TABLE_MAX_CHUNK_SIZE, DocumentChunk, chunk_document
from engine_py.rag.document_parse import DocumentParseError, parse_document


# ---------------------------------------------------------------------------
# 1. 切块器(纯 Markdown,零解析零 DB)
# ---------------------------------------------------------------------------
def _chunk_md(markdown: str, **kwargs) -> list[DocumentChunk]:
    return chunk_document(
        markdown,
        business_id=kwargs.get("business_id", "aurora"),
        source_url=kwargs.get("source_url", "demo.md"),
        category=kwargs.get("category", "document"),
        source_format=kwargs.get("source_format", "docx"),
        doc_title=kwargs.get("doc_title", "演示文档"),
    )


def test_table_stays_atomic_chunk():
    md = "# 会员规则\n\n## 积分门槛\n\n正文一句话。\n\n"
    md += "| 等级 | 门槛 | 权益 |\n| --- | --- | --- |\n| 银卡 | 1000 | 95 折 |\n| 金卡 | 5000 | 9 折 |\n"
    chunks = _chunk_md(md)
    tables = [c for c in chunks if c.content_type == "table"]
    assert len(tables) == 1, "小表格必须原子成块,严禁与段落混块或腰斩"
    assert "银卡" in tables[0].chunk_text and "9 折" in tables[0].chunk_text
    assert tables[0].header_path == "会员规则 > 积分门槛"
    assert tables[0].metadata_dict()["contentType"] == "table"


def test_long_table_splits_by_row_groups_with_repeated_header():
    rows = ["| 序号 | 规则细节 |", "| --- | --- |"]
    for i in range(60):
        rows.append(f"| {i} | 条款细节第 {i} 号:验收标准说明文字足够长以撑爆单块上限 |")
    md = "# 验收标准\n\n## 明细表\n\n" + "\n".join(rows) + "\n"
    chunks = _chunk_md(md)
    tables = [c for c in chunks if c.content_type == "table"]
    assert len(tables) >= 2, "超长表格必须按行组切开"
    assert all(len(c.chunk_text) <= TABLE_MAX_CHUNK_SIZE for c in tables)
    header_cell = "规则细节"
    assert all(header_cell in c.chunk_text for c in tables), "每个行组必须重复表头,BM25 词面锚点不丢"
    joined = "\n".join(c.chunk_text for c in tables)
    for i in range(60):
        assert f"| {i} |" in joined, f"行组切分不得丢行:第 {i} 行缺失"


def test_image_line_becomes_chunk_with_url_metadata():
    md = "# 安装指引\n\n## 示意图\n\n![部署拓扑图](/api/uploads/rag/abc123.png)\n\n后续说明文字。\n"
    chunks = _chunk_md(md)
    images = [c for c in chunks if c.content_type == "image"]
    assert len(images) == 1
    assert "部署拓扑图" in images[0].chunk_text
    assert images[0].image_url == "/api/uploads/rag/abc123.png"
    assert images[0].metadata_dict()["imageUrl"] == "/api/uploads/rag/abc123.png"
    assert any(c.content_type == "text" and "后续说明文字" in c.chunk_text for c in chunks)


def test_preheading_intro_not_dropped():
    """首标题前的概述段落以 doc_title 兜底为章节路径,严禁静默丢弃。"""
    md = "本产品定位为面向 Z 世代的潮流电商,核心指标是复购率。\n\n# 第一章\n\n正文。\n"
    chunks = _chunk_md(md, doc_title="产品需求概述")
    assert any("复购率" in c.chunk_text for c in chunks), "前置概述不得被丢弃"
    intro = next(c for c in chunks if "复购率" in c.chunk_text)
    assert intro.header_path == "产品需求概述"


def test_first_heading_upgrades_to_doc_title():
    md = "# 极光会员章程\n\n## 积分\n\n内容。\n"
    chunks = _chunk_md(md, doc_title="file_stem")
    assert all(c.doc_title == "极光会员章程" for c in chunks)
    assert chunks[0].header_path.startswith("极光会员章程")


def test_level2_first_heading_must_not_usurp_doc_title():
    """对抗审查(2026-10-17)修复回归:仅 `#` 级标题可升格文档标题。
    全 Heading 2 文档(无 # 根)的首个节标题不得抢位,兄弟节不得被嵌套为其子节。"""
    md = "## 总则\n\n总则内容。\n\n## 保修\n\n保修内容。\n\n## 赔付\n\n赔付内容。\n"
    chunks = _chunk_md(md, doc_title="服务手册")
    assert all(c.doc_title == "服务手册" for c in chunks), "无 # 根时沿用调用方 doc_title,严禁首个 ## 抢位"
    paths = [c.header_path for c in chunks if c.chunk_text.endswith("内容。")]
    assert paths == ["总则", "保修", "赔付"], f"同级节平铺不嵌套,实得 {paths}"
    assert not any(p.startswith("总则 >") for p in paths), "兄弟节严禁被嵌套为首节子节"


def test_long_single_row_table_not_dropped():
    """对抗审查(2026-10-17)修复回归:表体行被表头耗尽(单行超长表)时原样成块,
    严禁返回空列表让整张表静默消失(还连累文档被误诊为扫描件)。"""
    long_row = "| " + "x" * 1600 + " |"
    md = "# 明细\n\n" + long_row + "\n"
    chunks = _chunk_md(md)
    tables = [c for c in chunks if c.content_type == "table"]
    assert len(tables) == 1 and long_row in tables[0].chunk_text, "超长单行表必须保真成块"


def test_html_table_selfclosed_and_unterminated():
    """对抗审查(2026-10-17)修复回归:单行自闭合 HTML 表不得吞后续内容;
    未闭合 HTML 表遇标题行必须止步。"""
    md1 = "<table><tr><td>A1</td></tr></table>\n普通段落文字。\n<table><tr><td>B1</td></tr></table>\n"
    chunks1 = _chunk_md(md1)
    tables1 = [c for c in chunks1 if c.content_type == "table"]
    texts1 = [c.chunk_text for c in tables1]
    assert len(tables1) == 2, f"两张自闭合单行表应各自成块,实得 {len(tables1)}"
    assert not any("普通段落文字" in t for t in texts1), "段落严禁被吞进表格块"

    md2 = "<table><tr><td>未闭合</td></tr>\n后续行。\n\n## 后续标题\n\n标题下内容。\n"
    chunks2 = _chunk_md(md2)
    assert any(c.content_type == "text" and "标题下内容" in c.chunk_text for c in chunks2), (
        "未闭合表吞到文档尾会让后续标题与内容全部失联"
    )
    assert any(c.header_path == "后续标题" and c.content_type == "text" for c in chunks2), (
        "止步后标题必须正常入栈"
    )


def test_caption_with_backslashes_survives():
    r"""对抗审查(2026-10-17)修复回归:字幕含反斜杠序列(\1 \U C:\Users 字面 \n)
    不得炸 re.error 中断整批摄取,也不得被模板解析成真换行毁掉图片行。"""
    from engine_py.rag.document_ingest import _apply_caption

    url = "/api/uploads/rag/abc.png"
    md = f"![]({url})\n"
    for caption in ("增长 30\\d% 如图", "路径 C:\\Users\\demo 示意", "第\\1章节结构", "反斜杠\\结尾"):
        rewritten = _apply_caption(md, url, caption)
        assert rewritten.count("\n") == 1, f"字幕 {caption!r} 不得给图片行引入换行,实得 {rewritten!r}"
        assert f"]({url})" in rewritten and rewritten.startswith("![")
        assert "\\" not in rewritten.split("](")[0], f"反斜杠必须被净化,实得 {rewritten!r}"


def test_ordered_list_glue_preserved():
    md = "# SOP\n\n## 步骤\n\n1. 打开控制台\n2. 点击申请\n3. 确认提交\n\n## 其他\n\n尾段。\n"
    chunks = _chunk_md(md)
    sop = [c for c in chunks if "步骤" in c.header_path]
    assert len(sop) == 1, "有序列表必须粘连为原子块(knowledge_files 同纪律)"
    for step in ("打开控制台", "点击申请", "确认提交"):
        assert step in sop[0].chunk_text


# ---------------------------------------------------------------------------
# 2. 解析器(真 docling docx 规则后端,零模型下载)
# ---------------------------------------------------------------------------
def test_parse_docx_via_docling(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))  # 插图落 tmp,严禁写仓库 public/
    doc_path = build_docx(
        tmp_path / "会员章程.docx",
        [
            ("h1", "极光会员章程"),
            ("p", "本章程适用于极光潮品全部注册会员。"),
            ("h2", "积分规则"),
            ("p", "消费一元累计一分,积分年度有效。"),
            ("table", [["等级", "门槛"], ["银卡", "1000"], ["金卡", "5000"]]),
            ("h2", "会员标识"),
            ("image",),
        ],
    )
    parsed = parse_document(doc_path)
    assert parsed.source_format == "docx"
    assert parsed.doc_title == "极光会员章程"
    assert "积分规则" in parsed.markdown
    assert "银卡" in parsed.markdown and "|" in parsed.markdown, "表格须以管道表导出"
    assert len(parsed.image_urls) == 1
    assert parsed.image_urls[0].startswith("/api/uploads/rag/")
    # 插图真实落盘且 md 引用已改写
    local = tmp_path / "uploads" / "rag" / Path(parsed.image_urls[0]).name
    assert local.is_file(), "插图必须从 artifacts 搬到 uploads/rag"
    assert Path(parsed.image_urls[0]).name in parsed.markdown

    chunks = chunk_document(
        parsed.markdown,
        business_id="aurora",
        source_url="会员章程.docx",
        category="document",
        source_format=parsed.source_format,
        doc_title=parsed.doc_title or "会员章程",
    )
    assert any(c.content_type == "table" and "银卡" in c.chunk_text for c in chunks), "表格切块保真"
    assert any(c.content_type == "image" for c in chunks)


def test_doc_rejected_with_honest_message(tmp_path):
    doc = tmp_path / "legacy.doc"
    doc.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 32)
    with pytest.raises(DocumentParseError, match="另存为"):
        parse_document(doc)


def test_unsupported_suffix_rejected(tmp_path):
    doc = tmp_path / "page.rtf"
    doc.write_text("hello", encoding="utf-8")
    with pytest.raises(DocumentParseError, match="不支持"):
        parse_document(doc)


# ---------------------------------------------------------------------------
# 3. 摄取:覆盖重建 + metadata 增量键 + 租户隔离(密封 PG)
# ---------------------------------------------------------------------------
class _StubEmbeddings:
    """token 指示向量桩:词面余弦,确定性、全正(与检索侧 precomputed 同桩对齐)。"""

    def __init__(self, dim: int = 96):
        import hashlib

        self._dim = dim
        self._hash = hashlib.md5

    def _vec(self, text: str) -> list[float]:
        from engine_py.rag.contextual_rag import tokenize

        vec = [0.0] * self._dim
        for tok in tokenize(text):
            digest = int(self._hash(tok.encode()).hexdigest(), 16)
            vec[digest % self._dim] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    async def aembed_query(self, text_value: str) -> list[float]:
        return self._vec(text_value)


def _query_vec(text: str) -> list[float]:
    return _StubEmbeddings()._vec(text)


async def _ingest_docx(factory, monkeypatch, tmp_path: Path, name: str, blocks: list[tuple], business_id: str):
    from engine_py.rag import document_ingest as di

    monkeypatch.setattr(di, "get_embedding_model", lambda: _StubEmbeddings())
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    path = build_docx(tmp_path / name, blocks)
    return await di.ingest_document_file(path, business_id, caption_images=False)


def test_ingest_replaces_same_source_and_isolates_tenant(pg_factory, monkeypatch, tmp_path):
    async def _scenario() -> None:
        from engine_py.rag import contextual_rag as cr

        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))

        blocks_v1 = [
            ("h1", "退换货政策"),
            ("h2", "时效"),
            ("p", "签约版政策:15 天内可退。"),
        ]
        first = await _ingest_docx(pg_factory, monkeypatch, tmp_path, "退换货政策.docx", blocks_v1, "aurora")
        assert first.status == "ingested" and first.chunks == 1, "h1 无正文不成块,仅「时效」节 1 块"

        async with pg_factory.begin() as conn:
            count_v1 = (
                await conn.execute(text("SELECT COUNT(*) FROM rag_documents WHERE source_url = '退换货政策.docx'"))
            ).scalar_one()

        # 同名重传 = 版本演进:整组替换,行数不得堆叠
        blocks_v2 = [
            ("h1", "退换货政策"),
            ("h2", "时效"),
            ("p", "修订版政策:30 天内可退,吊牌完好为前提。"),
            ("h2", "例外"),
            ("p", "贴身衣物与定制品不支持退换。"),
        ]
        second = await _ingest_docx(pg_factory, monkeypatch, tmp_path, "退换货政策.docx", blocks_v2, "aurora")
        assert second.status == "ingested" and second.chunks == 2, "「时效」+「例外」两节"

        async with pg_factory.begin() as conn:
            count_v2 = (
                await conn.execute(text("SELECT COUNT(*) FROM rag_documents WHERE source_url = '退换货政策.docx'"))
            ).scalar_one()
            stale = (
                await conn.execute(
                    text("SELECT COUNT(*) FROM rag_documents WHERE chunk_text LIKE '%15 天内可退%'")
                )
            ).scalar_one()
            meta = (
                await conn.execute(
                    text(
                        "SELECT metadata ->> 'contentType', metadata ->> 'sourceFormat' "
                        "FROM rag_documents WHERE source_url = '退换货政策.docx' LIMIT 1"
                    )
                )
            ).first()
        assert count_v1 == first.chunks and count_v2 == second.chunks, "覆盖重建:行数与新版本一致,不得堆叠"
        assert stale == 0, "旧版本正文必须被整组清掉,严禁新旧并存检索漂移"
        assert meta[0] == "text" and meta[1] == "docx", "metadata 增量键必须落库"

        # 租户隔离:aurora 文档对 nike 零泄漏;跨租户同名不互删
        nike_blocks = [("h1", "Nike 会员条款"), ("h2", "等级"), ("p", "Nike 黑卡会员享生日双倍积分。")]
        await _ingest_docx(pg_factory, monkeypatch, tmp_path, "会员条款.docx", nike_blocks, "nike")

        aurora_hits = await cr.ContextualRAG("aurora").search_relevant_docs(
            "退换货 30 天 吊牌 例外", limit=3, precomputed_embedding=_query_vec("退换货 30 天 吊牌 例外")
        )
        assert aurora_hits
        assert all(h["businessId"] == "aurora" for h in aurora_hits)
        assert all("Nike" not in h["chunkText"] for h in aurora_hits)

        nike_hits = await cr.ContextualRAG("nike").search_relevant_docs(
            "会员 等级 黑卡 积分", limit=3, precomputed_embedding=_query_vec("会员 等级 黑卡 积分")
        )
        assert nike_hits
        assert all("aurora" != h["businessId"] for h in nike_hits)

    asyncio.run(_scenario())


def test_ingest_scanned_document_skips_honestly(pg_factory, monkeypatch, tmp_path):
    """扫描件(无文本层)诚实 skip,严禁写空壳行。"""
    from engine_py.rag import document_ingest as di

    async def _scenario() -> None:
        async with pg_factory.begin() as conn:
            # 前序测试的 ContextualRAG 检索会触发知识自愈播种(22 行)—— 先清场,
            # 断言「失败摄取零写行」才有意义
            await conn.execute(text("DELETE FROM rag_documents"))
        fake_pdf = tmp_path / "scanned.pdf"
        fake_pdf.write_bytes(b"%PDF-1.4\n" + b"\x00" * 64)  # 魔数真、内容空(非合法 PDF,docling 转换失败)
        monkeypatch.setattr(di, "get_embedding_model", lambda: _StubEmbeddings())
        result = await di.ingest_document_file(fake_pdf, "aurora", caption_images=False)
        assert result.status in ("failed", "skipped")
        assert result.reason, "失败/跳过必须携带诚实原因"

        async with pg_factory.begin() as conn:
            total = (await conn.execute(text("SELECT COUNT(*) FROM rag_documents"))).scalar_one()
        assert total == 0, "失败摄取严禁写行"

    asyncio.run(_scenario())
