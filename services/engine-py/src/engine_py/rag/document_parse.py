"""PDF/Word 双格式文档解析(docling)— 文档 RAG 的解析层。

与 knowledge_files.py(Markdown 知识文件)互补:本模块把 .pdf/.docx 经 docling
转成 Markdown(标题层级 + 管道表格 + 图片引用行),交由 document_chunker 按同一套
切片纪律(标题路径栈、贪心打包)切块。选型见 2026-10-17 需求裁决:Docling 一条
管线吃双格式、表格结构识别保真最好、CPU 可跑。

**为什么自建导出器而非 export_to_markdown**(2026-10-17 实测):docling 的
markdown 序列化对「不在阅读树里的图片」全模式静默丢弃(docx 内嵌图实测无树锚点,
doc.pictures 有、iterate_items 无),referenced 模式也只认本地路径不认 data URI。
故按 iterate_items 阅读序自拼 Markdown:标题层级(level-1)/表格单表导出/
有序列表编号/流内图片就地落位;未进阅读流的图片追加「附录:文档插图」——
内容不丢、诚实可检,严禁静默丢弃。

诚实边界(数据诚实律):
- 老式 .doc 二进制格式不解析,显式报错要求另存为 .docx(严禁猜测转换);
- 扫描型 PDF:PDF 管线内置 RapidOCR(PP-OCRv6)自动提取(2026-10-18 实证,图片型
  PDF 全文可读且带标题层级;P0→PO 类字符混淆属 OCR 固有误差,provenance 诚实不变);真正空文档由调用方按「空内容」诚实跳过;
- PARTIAL_SUCCESS 转换结果照常返回但在 partial 标记上如实暴露(如个别页超时);
- 无位图数据的图片位不生成引用行,严禁虚构占位。

字幕(caption)由 ingest 层按需 VLM 生成,本模块不调模型。
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# HF 镜像:docling 首次转换 PDF 会经 huggingface_hub 拉版面/表格识别权重,
# 与 llm/chat.py 的 fastembed 同一套镜像纪律(必须在 docling import 前设置,
# 故放模块顶;docling 本体惰性导入,不拖慢 gateway 进程启动)。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# 图片引用行前缀(与 gateway /api/uploads StaticFiles 挂载对齐)
IMAGE_URL_PREFIX = "/api/uploads/rag"

_IMAGE_MARKER_RE = re.compile(r"^@@IMAGE:(\d+)@@$")
# 文档标题取首个 1-2 级标题(自建导出里 doc title 在 L2,故 # 与 ## 皆可)
_FIRST_TITLE_RE = re.compile(r"^#{1,2}\s+(.+?)\s*$", re.MULTILINE)

_SUPPORTED_SUFFIXES = {".pdf": "pdf", ".docx": "docx"}
_MIME_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}
_SKIP_LABELS = {"page_header", "page_footer"}  # 页眉页脚严禁污染知识切片

# zip 炸弹成员预读闸(v2 在案残余收口,2026-10-18):docx 是 zip 容器,
# 20MB 压缩体按 ~1032:1 极限 deflate 可展开 GB 级 XML 全量进 docling 解析器。
# 落盘后、转换前按 zip 头声明的解压尺寸预读(零解压成本),超限诚实拒绝。
_DOCX_MAX_MEMBER_UNCOMPRESSED = 64 * 1024 * 1024  # 单成员 64MB
_DOCX_MAX_TOTAL_UNCOMPRESSED = 200 * 1024 * 1024  # 解压总量 200MB


def _guard_docx_zip(path: Path) -> None:
    """docx 容器成员预读闸:单成员/解压总量超限即诚实拒绝(严禁全量进解析器)。"""
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            total = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if info.file_size > _DOCX_MAX_MEMBER_UNCOMPRESSED:
                    raise DocumentParseError(
                        f"文档内部成员 {info.filename} 解压后约 {info.file_size // (1024 * 1024)}MB,"
                        f"超过 {_DOCX_MAX_MEMBER_UNCOMPRESSED // (1024 * 1024)}MB 上限,已拒绝处理"
                    )
                total += info.file_size
                if total > _DOCX_MAX_TOTAL_UNCOMPRESSED:
                    raise DocumentParseError(
                        f"文档解压后总量超过 {_DOCX_MAX_TOTAL_UNCOMPRESSED // (1024 * 1024)}MB 上限,已拒绝处理"
                    )
    except zipfile.BadZipFile as err:
        raise DocumentParseError(f"docx 容器损坏或非 zip 结构: {err}") from err


class DocumentParseError(RuntimeError):
    """解析失败(格式不支持/转换失败)——调用方必须把 message 原样透出,严禁吞成泛化错误。"""


def uploads_root() -> Path:
    """uploads 根目录:与 gateway chat.py / vision analyzer 同约定
    (``UPLOADS_DIR`` env 可覆写,缺省仓库根 public/uploads,已在 .gitignore)。"""
    env = os.environ.get("UPLOADS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[5] / "public" / "uploads"


def rag_images_dir() -> Path:
    """文档插图落盘目录(uploads/rag 子目录,独立于聊天图片命名空间)。"""
    target = uploads_root() / "rag"
    target.mkdir(parents=True, exist_ok=True)
    return target


@dataclass
class ParsedDocument:
    """单份文档的解析产物:Markdown 骨架 + 已落盘的插图 URL + 结构化负载。

    table_payloads 与 markdown 中的管道表**按出现顺序一一对应**(同一遍
    iterate_items 产出,失败渲染的表两边都不留);chart_payloads 以插图
    URL 为键,只含有损数据的来源(当前 = docx 原生 chart 缓存,零读数误差;
    PDF granite-vision 抽数与 VLM 兜底在 ingest 层按需补)。
    """

    markdown: str
    source_format: str  # pdf | docx
    image_urls: list[str] = field(default_factory=list)  # /api/uploads/rag/*.png(仅位图成功的图片位)
    table_payloads: list[dict | None] = field(default_factory=list)  # {"headers": [...], "rows": [[...]]}
    chart_payloads: dict[str, dict] = field(default_factory=dict)  # url → {"headers","rows","kind","title","provenance"}
    doc_title: str | None = None
    partial: bool = False  # PARTIAL_SUCCESS:部分页失败,内容不完整 —— 如实暴露


def parse_document(path: Path) -> ParsedDocument:
    """单文档解析(同步 CPU 密集,调用方须 asyncio.to_thread 下放)。"""
    suffix = path.suffix.lower()
    source_format = _SUPPORTED_SUFFIXES.get(suffix)
    if source_format is None:
        if suffix == ".doc":
            raise DocumentParseError(
                "老式 .doc 二进制格式暂不支持,请先用 Word/WPS 另存为 .docx 或导出 PDF 后重试"
            )
        raise DocumentParseError(f"不支持的文档格式 {suffix or '(无扩展名)'},仅支持 .pdf / .docx")

    # max_num_pages 防御页数无界(docling 缺省 sys.maxsize,2026-10-17 对抗审查:
    # 恶意/异常文档逐页 2x 渲染可在网关进程内造成分钟级占用)。
    if source_format == "docx":
        _guard_docx_zip(path)  # zip 炸弹成员预读闸(v2 在案残余收口,2026-10-18)
    result = _get_converter().convert(str(path), max_num_pages=500)
    status = str(result.status.value) if result.status is not None else ""
    if status not in ("success", "partial_success"):
        errors = "; ".join(err.error_message for err in (result.errors or []))
        raise DocumentParseError(f"文档转换失败(status={status or 'unknown'}): {errors or '无错误详情'}")

    markdown, image_urls, table_payloads, chart_payloads = _export_markdown(
        result.document,
        provenance=("native" if source_format == "docx" else "extracted"),
    )
    title_match = _FIRST_TITLE_RE.search(markdown)
    return ParsedDocument(
        markdown=markdown,
        source_format=source_format,
        image_urls=image_urls,
        table_payloads=table_payloads,
        chart_payloads=chart_payloads,
        doc_title=title_match.group(1).strip() if title_match else None,
        partial=(status == "partial_success"),
    )


def _export_markdown(doc, provenance: str) -> tuple[str, list[str], list[dict | None], dict[str, dict]]:
    """按 iterate_items 阅读序自拼 Markdown,返回 (markdown, 插图 URL 序列,
    表格结构化负载序列, 图表结构化负载 dict)。

    provenance:图表负载的数据来源分级(docx → native / pdf → extracted),
    由 parse_document 按格式传入。

    标题层级 = 阅读树深度 - 1(实测 docx:标题 L2/节 L3/小节 L4 → #/##/###,
    绝对基准漂移无妨 —— chunker 会把首个 `#` 强制压栈为 1 级,相对嵌套保真);
    表格走单表导出(管道表)+ export_to_dataframe 结构化负载(按渲染序对齐,
    供确定性聚合器计算);有序列表按连续 run 重编号(SOP 步骤语义不丢);
    流内图片就地落位;未进阅读流的图片(docx 内嵌图实测无树锚点)追加附录。
    """
    lines: list[str] = []
    image_urls: list[str] = []
    image_markers: list[str | None] = []  # 与文件内标记序对齐;None = 该图片位无位图,删行
    chart_payloads: dict[str, dict] = {}
    table_payloads: list[dict | None] = []
    yielded_picture_refs: set[str] = set()
    ordered_counter = 0

    for item, level in doc.iterate_items():
        kind = type(item).__name__
        label = str(getattr(item, "label", "") or "")
        if label in _SKIP_LABELS:
            ordered_counter = 0
            continue

        if kind == "SectionHeaderItem" or label in ("title", "section_header"):
            text = (getattr(item, "text", "") or "").strip()
            if text:
                md_level = max(1, min((level or 2) - 1, 6))
                lines += ["", f"{'#' * md_level} {text}", ""]
            ordered_counter = 0
        elif kind == "TableItem":
            try:
                table_md = (item.export_to_markdown(doc) or "").strip()
            except Exception as err:
                print(f"[DocParse] 表格导出失败,降级丢弃该表(不虚构内容): {err}")
                table_md = ""
            if table_md:
                # 标记锚定:行组切分会把一张表扇出 k 个切片,序号对齐会错缝
                # (2026-10-17 v2 对抗审查 high)—— 改为标记锚定,切片侧每片
                # 按 marker 取同一份 payload(全表计算面,任一片被召回都可算)
                lines += ["", f"<!--DOC-TABLE:{len(table_payloads)}-->", table_md, ""]
                table_payloads.append(_table_payload(item, doc))
            ordered_counter = 0
        elif kind == "PictureItem":
            yielded_picture_refs.add(str(item.self_ref))
            url = _persist_picture(item.image)
            chart_payload = _native_chart_payload(item, provenance)
            if url:
                image_markers.append(url)  # 与文件内 @@IMAGE:序号@@ 一一对应(序号 = len(image_urls))
                image_urls.append(url)
                if chart_payload:
                    chart_payloads[url] = chart_payload
                lines += ["", f"@@IMAGE:{len(image_markers) - 1}@@", ""]
            elif chart_payload:
                # 无位图的原生 chart(实测:docx 内嵌 chart 不经 LibreOffice 渲染就没有
                # 位图):数据以管道表就地渲染,负载按渲染序进 table_payloads —— 它本就是
                # 文档自有数据(零读数误差),聚合器按 tableData 消费;严禁静默丢弃
                rendered = _render_pipe_table(chart_payload)
                if rendered:
                    lines += ["", f"<!--DOC-TABLE:{len(table_payloads)}-->", rendered, ""]
                    table_payloads.append({"headers": chart_payload["headers"], "rows": chart_payload["rows"]})
            else:
                image_markers.append(None)
                lines += ["", f"@@IMAGE:{len(image_markers) - 1}@@", ""]  # 无位图占位,落位时删行
            ordered_counter = 0
        elif kind == "ListItem" or label == "list_item":
            text = (getattr(item, "text", "") or "").strip()
            if text:
                if getattr(item, "enumerated", False):
                    ordered_counter += 1
                    lines.append(f"{ordered_counter}. {text}")
                else:
                    ordered_counter = 0
                    lines.append(f"- {text}")
        else:
            text = (getattr(item, "text", "") or "").strip()
            if text:
                lines += [text, ""]
            ordered_counter = 0

    # 未进阅读流的图片(docx 内嵌图实测如此):附录追加,内容不丢、诚实可检
    leftovers = [pic for pic in doc.pictures if str(pic.self_ref) not in yielded_picture_refs]
    if leftovers:
        lines += ["", "## 附录:文档插图", ""]
        for pic in leftovers:
            url = _persist_picture(pic.image)
            chart_payload = _native_chart_payload(pic, provenance)
            if url:
                lines.append(f"![]({url})")
                image_urls.append(url)
                if chart_payload:
                    chart_payloads[url] = chart_payload
            elif chart_payload:
                rendered = _render_pipe_table(chart_payload)
                if rendered:
                    lines += ["", f"<!--DOC-TABLE:{len(table_payloads)}-->", rendered, ""]
                    table_payloads.append({"headers": chart_payload["headers"], "rows": chart_payload["rows"]})

    # 标记落位:有 URL 换引用行,无位图的图片位删行(严禁空壳占位进切块)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        marker = _IMAGE_MARKER_RE.match(stripped)
        if marker:
            index = int(marker.group(1))
            url = image_markers[index] if index < len(image_markers) else None
            if url:
                out.append(f"![]({url})")
            continue
        out.append(line)
    return "\n".join(out), image_urls, table_payloads, chart_payloads


def _table_payload(item, doc) -> dict | None:
    """TableItem → {"headers": [...], "rows": [[...]]}(字符串化,全单元格保序);
    失败诚实 None(管道表文本照常入索引,只是没有计算面)。"""
    try:
        frame = item.export_to_dataframe(doc)
        headers = [str(c) for c in frame.columns]
        rows = [[("" if v is None else str(v)) for v in row] for row in frame.values]
        if not headers or not rows:
            return None
        return {"headers": headers, "rows": rows}
    except Exception as err:
        print(f"[DocParse] 表格结构化失败(文本索引不受影响,计算面缺失): {err}")
        return None


def _native_chart_payload(item, provenance: str) -> dict | None:
    """图片位上的图表数据 → 结构化负载。provenance 按来源分级(数据诚实律):
    - docx → native:OOXML 缓存重建,零模型零读数误差,结果无需标注;
    - pdf → extracted:granite-vision 抽数(do_chart_extraction),VLM 读数,
      聚合结果强制「读数误差」标注。
    无负载返回 None(交由 ingest 层 VLM 兜底)。"""
    meta = getattr(item, "meta", None)
    tabular = getattr(meta, "tabular_chart", None) if meta else None
    if tabular is None:
        return None
    try:
        chart_data = tabular.chart_data
        grid = [["" for _ in range(chart_data.num_cols)] for _ in range(chart_data.num_rows)]
        for cell in chart_data.table_cells:
            grid[cell.start_row_offset_idx][cell.start_col_offset_idx] = cell.text
        if not grid or all(not any(row) for row in grid):
            return None  # 空网格/全空退化 grid:v2 审查实证 [[]] truthy 会占 payload 槽致后续表错位
        return {
            "kind": "tabular",
            "title": getattr(tabular, "title", None) or getattr(chart_data, "title", None),
            "headers": grid[0],
            "rows": grid[1:] if len(grid) > 1 else [],
            "provenance": provenance,
        }
    except Exception as err:
        print(f"[DocParse] 图表数据重建失败,降级无计算面: {err}")
        return None


def _render_pipe_table(payload: dict) -> str:
    """{"headers","rows"} → 管道表 markdown(chunker 的表格原子块直接消费)。"""
    headers = [str(h) for h in (payload.get("headers") or [])]
    rows = [[str(c) for c in row] for row in (payload.get("rows") or [])]
    if not headers:
        return ""
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join([" --- "] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def _persist_picture(image_ref) -> str | None:
    """单个图片位 → uploads/rag 文件 + 静态 URL;无位图数据返回 None(诚实无图)。"""
    if image_ref is None:
        return None
    uri = str(image_ref.uri or "")
    dest_stem = f"{uuid.uuid4().hex}"
    if uri.startswith("data:"):
        header, _, payload = uri.partition(",")
        mime = header[5:].partition(";")[0] or "image/png"
        ext = _MIME_EXT.get(mime)
        if ext is None:
            return None
        try:
            data = base64.b64decode(payload)
        except Exception as err:
            print(f"[DocParse] 插图 base64 解码失败,该图片位降级无位图: {err}")
            return None
        if not data:
            return None
        dest = rag_images_dir() / f"{dest_stem}{ext}"
        dest.write_bytes(data)
        return f"{IMAGE_URL_PREFIX}/{dest.name}"
    uri = uri.removeprefix("file://")
    src = Path(uri)
    if src.is_file():
        dest = rag_images_dir() / f"{dest_stem}{src.suffix.lower() or '.png'}"
        shutil.copy(src, dest)
        return f"{IMAGE_URL_PREFIX}/{dest.name}"
    return None


@lru_cache(maxsize=1)
def _get_converter():
    """DocumentConverter 单例:构造零成本,模型权重在首次 PDF 转换时才按需下载
    (HF 镜像见模块顶);PDF 管线开 generate_picture_images 让插图位图随转换产出
    (缺省关)。docx 走规则后端,不涉模型下载,图片以内嵌 data URI 携带。

    granite-vision 抽数层(v2,2026-10-17):``RAG_DOC_CHART_EXTRACTION=1`` 时开
    do_chart_extraction —— bar/pie/line 图表经 granite-vision 读数为结构化表格
    (provenance=extracted,聚合结果带读数误差标注)。缺省关:预设模型权重
    数 GB、首用下载 + 逐图 VLM 推理都在网关进程内,属显式运维决策;
    preset 经 ``RAG_DOC_CHART_PRESET`` 可选(缺省 granite_vision_v3_3 =
    Chart2CSV 专用 2B,基准 60.1)。"""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions(
        generate_picture_images=True,
        images_scale=2.0,
    )
    if os.environ.get("RAG_DOC_CHART_EXTRACTION", "0") == "1":
        from docling.datamodel.chart_extraction_options import ChartExtractionVlmEngineOptions

        pipeline_options.do_chart_extraction = True
        preset = os.environ.get("RAG_DOC_CHART_PRESET", "granite_vision_v3_3")
        pipeline_options.chart_extraction_options = ChartExtractionVlmEngineOptions.from_preset(preset)
        print(f"[DocParse] granite-vision 图表抽数已启用(preset={preset};首用将下载模型权重)")
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
