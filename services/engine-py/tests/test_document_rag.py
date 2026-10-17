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


# ---------------------------------------------------------------------------
# 4. 结构化计算面(v2):tableData/chartData 缝接 + 确定性聚合器
# ---------------------------------------------------------------------------
def test_coerce_number_variants():
    from engine_py.rag.aggregator import coerce_number

    assert coerce_number("1,000") == 1000
    assert coerce_number("95%") == 0.95
    assert coerce_number("310万") == 3_100_000
    assert coerce_number("2.5亿") == 250_000_000
    assert coerce_number(" 6200 ") == 6200
    assert coerce_number("不限量") is None, "非数值必须诚实 None,严禁猜"
    assert coerce_number("") is None
    assert coerce_number(None) is None


def test_pick_op_and_column_disambiguation():
    from engine_py.rag.aggregator import pick_column, pick_op

    assert pick_op("表格里所有项目所需积分的总计") == "sum"
    assert pick_op("平均响应时长") == "avg"
    assert pick_op("最高的门店") == "max"
    assert pick_op("政策内容是什么") is None, "非计算问句必须 None"
    assert pick_op("最大和最小的差值") is None, "复合意图(双操作)交回原链路"

    headers = ["兑换项目", "所需积分", "库存策略"]
    assert pick_column(headers, "所需积分的总计是多少") == "所需积分"
    assert pick_column(headers, "兑换项目的总计") == "兑换项目", "精确子串命中"
    assert pick_column(headers, "门槛的合计") is None, "「门槛」是语义同义词,规则层不懂 → 诚实 None(交 LLM 闭集或降级)"
    assert pick_column(["退款金额", "订单金额"], "金额的总计是多少") is None, "「金额」同中两列 → 歧义 None"


def test_aggregate_math_over_table_data():
    from engine_py.rag.aggregator import aggregate

    data = {
        "headers": ["兑换项目", "所需积分"],
        "rows": [["10 元优惠券", "1000"], ["帆布袋", "2000"], ["保温杯", "5000"], ["蓝牙音箱", "12000"]],
    }
    assert aggregate(data, "所需积分", "sum") == 20000
    assert aggregate(data, "所需积分", "avg") == 5000
    assert aggregate(data, "所需积分", "max") == 12000
    assert aggregate(data, "所需积分", "min") == 1000
    assert aggregate(data, None, "count") == 4
    assert aggregate(data, "兑换项目", "sum") is None, "非数值列严禁聚合,诚实 None"
    assert aggregate(data, "不存在的列", "sum") is None


def test_parse_native_chart_docx_yields_chart_payload(tmp_path):
    """docx 原生 Word chart → parse 层 chart_payloads(零模型无损提取,provenance=native)。

    OOXML 逐字节对齐真实 Word 导出形状(XML 声明/c:title/formatCode/正规 extent)
    —— 缺声明或 1x1 extent 时 docling-parse 会静默丢掉整个 drawing 实测。
    """
    import zipfile

    C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"

    def _pt(idx, val):
        return f'<c:pt idx="{idx}"><c:v>{val}</c:v></c:pt>'

    chart_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<c:chartSpace xmlns:c="{C}" xmlns:a="{A}" xmlns:r="{R}">'
        "<c:chart><c:plotArea><c:barChart><c:barDir val=\"col\"/><c:ser>"
        f'<c:tx><c:strRef><c:f>Sheet1!$B$1</c:f><c:strCache><c:ptCount val="1"/>{_pt(0, "兑换量")}</c:strCache></c:strRef></c:tx>'
        f'<c:cat><c:strRef><c:f>Sheet1!$A$2:$A$5</c:f><c:strCache><c:ptCount val="4"/>'
        + "".join(_pt(i, q) for i, q in enumerate(["Q1", "Q2", "Q3", "Q4"]))
        + "</c:strCache></c:strRef></c:cat>"
        '<c:val><c:numRef><c:f>Sheet1!$B$2:$B$5</c:f><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="4"/>'
        + "".join(_pt(i, v) for i, v in enumerate([120, 185, 240, 310]))
        + "</c:numCache></c:numRef></c:val></c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>"
    )
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" xmlns:a="{A}" xmlns:c="{C}"><w:body>'
        f'<w:p><w:r><w:t>季度兑换量:</w:t></w:r></w:p>'
        f'<w:p><w:r><w:drawing><wp:inline><wp:extent cx="5486400" cy="3200400"/>'
        f'<a:graphic><a:graphicData uri="{C}"><c:chart r:id="rId1"/></a:graphicData></a:graphic>'
        f"</wp:inline></w:drawing></w:r></w:p></w:body></w:document>"
    )
    path = tmp_path / "native.docx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        z.writestr("word/document.xml", doc_xml)
        z.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="charts/chart1.xml"/></Relationships>',
        )
        z.writestr("word/charts/chart1.xml", chart_xml)

    parsed = parse_document(path)
    # 无位图的原生 chart:数据以管道表就地渲染,负载按渲染序进 table_payloads
    # (文档自有数据 = 零读数误差,聚合器按 tableData 消费,无需 provenance 标注)
    assert len(parsed.table_payloads) == 1, "原生 chart 数据必须以结构化表落地,严禁静默丢弃"
    payload = parsed.table_payloads[0]
    assert payload["rows"] == [["Q1", "120"], ["Q2", "185"], ["Q3", "240"], ["Q4", "310"]], "缓存值必须原样无损"
    assert "兑换量" in payload["headers"]

    chunks = chunk_document(
        parsed.markdown,
        business_id="aurora",
        source_url="native.docx",
        category="document",
        source_format="docx",
        doc_title="季度兑换量",
    )
    table_chunks = [c for c in chunks if c.content_type == "table"]
    assert any("120" in c.chunk_text and "310" in c.chunk_text for c in table_chunks), "图表数据成为表格原子块(检索面)"


def test_table_payloads_stitch_and_metadata(pg_factory, monkeypatch, tmp_path):
    """摄取 → 召回切片 metadata 携带 tableData;try_aggregate 端到端出数。"""

    async def _scenario() -> None:
        from engine_py.rag import contextual_rag as cr
        from engine_py.rag.aggregator import format_result, try_aggregate

        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))

        blocks = [
            ("h1", "积分兑换规则"),
            ("p", "会员可用积分兑换以下礼品。"),
            ("table", [["兑换项目", "所需积分"], ["10 元优惠券", "1000"], ["帆布袋", "2000"], ["保温杯", "5000"]]),
        ]
        ingested = await _ingest_docx(pg_factory, monkeypatch, tmp_path, "积分兑换规则.docx", blocks, "aurora")
        assert ingested.status == "ingested"

        hits = await cr.ContextualRAG("aurora").search_relevant_docs(
            "积分兑换 礼品 门槛", limit=3, precomputed_embedding=_query_vec("积分兑换 礼品 门槛"), min_score=0.1
        )
        assert hits
        table_hit = next((h for h in hits if (h.get("metadata") or {}).get("tableData")), None)
        assert table_hit is not None, "表格切片必须携带 tableData 计算面"
        assert table_hit["metadata"]["tableData"]["headers"] == ["兑换项目", "所需积分"]
        assert table_hit["metadata"]["tableData"]["rows"] == [["10 元优惠券", "1000"], ["帆布袋", "2000"], ["保温杯", "5000"]]

        result = try_aggregate("这些礼品所需积分的总计是多少", hits)
        assert result is not None and result["value"] == 8000, "确定性聚合必须精确(sum=8000)"
        assert result["annotated"] is False, "表格结构化数据无需读数误差标注"
        summary = format_result(result)
        assert "8,000" in summary and "确定性代码计算" in summary, "千分位全精度渲染"

        assert try_aggregate("政策内容是什么", hits) is None, "非计算问句必须 None(回落原链路)"

    asyncio.run(_scenario())


def test_vlm_chart_fallback_stitch(pg_factory, monkeypatch, tmp_path):
    """原生数据缺席时 VLM 结构化读数回落(provenance=vlm,聚合结果带误差标注)。"""

    async def _scenario() -> None:
        from engine_py.rag import document_ingest as di
        from engine_py.rag.aggregator import format_result, try_aggregate
        from engine_py.rag.contextual_rag import ContextualRAG

        async with pg_factory.begin() as conn:
            await conn.execute(text("DELETE FROM rag_documents"))

        async def _fake_enrich(image_url):
            return "文档插图:柱状图展示四季度兑换量", {
                "kind": "tabular",
                "title": None,
                "headers": ["类别", "数值"],
                "rows": [["Q1", "120"], ["Q2", "185"], ["Q3", "240"], ["Q4", "310"]],
                "provenance": "vlm",
            }

        monkeypatch.setattr(di, "_vlm_enrich", _fake_enrich)
        monkeypatch.setattr(di, "get_embedding_model", lambda: _StubEmbeddings())
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))

        path = build_docx(
            tmp_path / "兑换量图表.docx",
            [("h1", "季度兑换量"), ("p", "下图给出各季度兑换量:"), ("image",)],
        )
        ingested = await di.ingest_document_file(path, "aurora", caption_images=True)
        assert ingested.status == "ingested"

        hits = await ContextualRAG("aurora").search_relevant_docs(
            "季度兑换量", limit=3, precomputed_embedding=_query_vec("季度兑换量"), min_score=0.1
        )
        chart_hit = next((h for h in hits if (h.get("metadata") or {}).get("chartData")), None)
        assert chart_hit is not None, "VLM 读数必须作为 chartData 缝接进图片切片"
        assert chart_hit["metadata"]["chartData"]["provenance"] == "vlm"

        result = try_aggregate("四个季度兑换量加起来一共多少", hits)
        assert result is not None and result["value"] == 855
        assert result["annotated"] is True, "VLM 读数的聚合结果必须带读数误差标注"
        assert "读数误差" in format_result(result)

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# 5. v2 对抗审查回归:锚定缝接 / 筛选意图 / count / 格式化 / 类型闸
# ---------------------------------------------------------------------------
def test_marker_anchor_survives_row_group_split():
    """v2 审查 high 回归:行组切分扇出 k 片时,每片都挂同一份全表 payload,
    后续表格的 payload 不得错缝到大表续片(实测曾静默算错账)。"""
    long_rows = ["| 序号 | 明细金额 |", "| --- | --- |"] + [
        f"| {i} | 金额明细第 {i} 行,附带足够长的说明文字以撑爆行组上限 |" for i in range(40)
    ]
    md = (
        "# 财务明细\n\n"
        "<!--DOC-TABLE:0-->\n"
        + "\n".join(long_rows)
        + "\n\n<!--DOC-TABLE:1-->\n\n| 项目 | 数量 |\n| --- | --- |\n| 门店数 | 5 |\n"
    )
    payloads = [
        {"headers": ["序号", "明细金额"], "rows": [[str(i), str(100 + i)] for i in range(40)]},
        {"headers": ["项目", "数量"], "rows": [["门店数", "5"]]},
    ]
    chunks = chunk_document(md, business_id="aurora", source_url="f.docx", category="document",
                            source_format="docx", doc_title="财务明细", table_payloads=payloads)
    big_pieces = [c for c in chunks if c.content_type == "table" and "明细金额" in c.chunk_text]
    small = [c for c in chunks if c.content_type == "table" and "门店数" in c.chunk_text]
    assert len(big_pieces) >= 2, "长表应扇出多片"
    assert all(c.table_data is payloads[0] for c in big_pieces), "大表每一片都挂同一份全表 payload"
    assert small and small[0].table_data is payloads[1], "后续表挂自己的 payload,严禁错缝到大表续片"


def test_filter_and_row_intent_questions_return_none():
    """v2 审查 high 回归:条件聚合(超过/以下)与行级定位(北京)必须诚实 None ——
    聚合器无谓词模型,整列求和曾以确定性权威口径算错账。"""
    from engine_py.rag.aggregator import try_aggregate

    data = {
        "headers": ["城市", "销售额"],
        "rows": [["北京", "100"], ["上海", "200"], ["广州", "300"]],
        "provenance": "native",
    }
    hits = [{"sourceUrl": "t.docx", "headerPath": "t", "metadata": {"tableData": data}}]
    assert try_aggregate("北京销售额合计是多少", hits) is None, "行级定位曾拿全城市总和 600 冒充北京"
    assert try_aggregate("销售额超过150的一共多少", hits) is None, "条件聚合曾拿全表总和冒充筛选结果"
    assert try_aggregate("销售额加起来一共多少", hits) is not None, "无过滤的全列聚合照常可算"
    assert try_aggregate("各城市销售额加起来一共多少", hits) is None, "「城市+销售额」双列精确命中 = 维度歧义,诚实 None"


def test_count_honors_column_and_word_overlap_gate():
    """v2 审查 medium 回归:count 带列时数该列数值单元格;无词面交集的无关
    表格严禁产出权威行数。"""
    from engine_py.rag.aggregator import try_aggregate

    data = {
        "headers": ["城市", "销售额"],
        "rows": [["北京", "100"], ["上海", "abc"], ["广州", "300"]],
    }
    hits = [{"sourceUrl": "t.docx", "headerPath": "t", "metadata": {"tableData": data}}]
    result = try_aggregate("销售额列有几个有效数值", hits)
    assert result is not None and result["value"] == 2, "count 带列必须数数值单元格(abc 非数值)"
    unrelated = [{"sourceUrl": "u.docx", "headerPath": "u", "metadata": {"tableData": {
        "headers": ["SKU", "库存"], "rows": [["A", "1"], ["B", "2"]],
    }}}]
    assert try_aggregate("销售额有几个有效数值", unrelated) is None, "问句与表零词面交集 → None"


def test_percent_column_sum_refused_and_avg_annotated():
    """v2 审查 medium 回归:百分比列 sum 语义可疑必须拒绝;avg/max/min 还原
    百分数呈现(「合计为 2.7」真值 270% 曾裸出)。"""
    from engine_py.rag.aggregator import format_result, try_aggregate

    data = {
        "headers": ["月份", "增长率"],
        "rows": [["5月", "50%"], ["6月", "60%"]],
    }
    hits = [{"sourceUrl": "g.docx", "headerPath": "g", "metadata": {"tableData": data}}]
    assert try_aggregate("两个月增长率加起来一共多少", hits) is None, "百分比列 sum 必须拒绝"
    result = try_aggregate("两个月增长率的平均值", hits)
    assert result is not None and result["percent"] is True
    assert "55%" in format_result(result), "avg 必须还原百分数呈现"


def test_large_number_never_scientific_notation():
    """v2 审查 medium 回归:%g 曾把 ≥1e6 渲染成「6.2e+06」、>6 位有效数静默截断,
    与「确定性精确计算」自相矛盾。"""
    from engine_py.rag.aggregator import format_result

    out = format_result({"value": 6200000.0, "op": "sum", "column": "GMV", "source": "s", "headerPath": "", "percent": False})
    assert "6,200,000" in out and "e+" not in out
    out = format_result({"value": 12345678.0, "op": "sum", "column": "GMV", "source": "s", "headerPath": "", "percent": False})
    assert "12,345,678" in out, "12 位整数必须全精度,严禁 6 位有效数截断"
    out = format_result({"value": 0.55, "op": "avg", "column": "r", "source": "s", "headerPath": "", "percent": False})
    assert "0.55" in out


def test_non_dict_payload_rejected_without_crash():
    """v2 审查 medium 回归:metadata.tableData 可被 admin 任意 JSON 写成 list/str,
    聚合器必须类型闸跳过,严禁 AttributeError 炸掉 grounding_block。"""
    from engine_py.rag.aggregator import try_aggregate

    hits = [
        {"sourceUrl": "bad.docx", "headerPath": "b", "metadata": {"tableData": ["not", "a", "dict"]}},
        {"sourceUrl": "bad2.docx", "headerPath": "b", "metadata": {"tableData": "string 负载"}},
        {"sourceUrl": "good.docx", "headerPath": "g", "metadata": {"tableData": {
            "headers": ["项目", "数量"], "rows": [["门店", "5"]],
        }}},
    ]
    result = try_aggregate("数量一共多少", hits)
    assert result is not None and result["value"] == 5, "非法负载跳过后,合法表照常可算"
