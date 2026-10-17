"""文档 Markdown → 知识切片(document_chunker)— 表格原子块纪律。

消费 document_parse 的 Markdown 产物(docling 导出:标题层级 + 管道表格 +
图片引用行),产出可写入 rag_documents 的切片。切片纪律与 knowledge_files
同源(标题路径栈、有序列表原子、≤500 字符贪心打包,复用同一实现),在此
基础上加三条文档特有规则(2026-10-17 需求裁决):

1. **表格 = 原子块**:管道表格(docling 复杂表退化的 HTML 表格同样成块)
   永不与段落混块、永不从中间切断 —— 验收标准/字段定义类表格被精确问到
   单元格时上下文完整;超长管道表按行组切分,每组重复表头行(BM25 词面
   锚点不因切分丢失);
2. **图片 = 独立块**:alt 文本即字幕(VLM 生成的描述由 ingest 写在 alt 里),
   图片 URL 进 metadata.imageUrl 供二期富卡片回显;
3. **首标题前的前置段落不丢**:PRD 概述常在第一个 ## 之前 —— 以 doc_title
   兜底为章节路径,严禁静默丢弃(knowledge_files 的 pre-heading 丢弃语义
   在文档域不适用,概述恰是常被问到的部分)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .knowledge_files import KnowledgeChunk, _pack_blocks, _split_blocks

# 表格原子块上限:表格信息密度远高于散文(全是词,无虚词),允许到 1500 字符;
# 再长按行组切。上限内单表独立成 chunk,严禁为凑 500 把表腰斩。
TABLE_MAX_CHUNK_SIZE = 1500

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_MD_IMAGE_LINE_RE = re.compile(r"^!\[([^\]]*)\]\((/api/uploads/[^)]+)\)\s*$")
_HTML_TABLE_OPEN_RE = re.compile(r"^<table[ >]", re.IGNORECASE)


@dataclass
class DocumentChunk(KnowledgeChunk):
    """文档切片:在 KnowledgeChunk 之上携带内容类型与图片引用(增量键,
    不破坏 admin 列表/_rag_item 既有 metadata 消费方)。"""

    content_type: str = "text"  # text | table | image
    image_url: str | None = None
    source_format: str = "pdf"  # pdf | docx

    def metadata_dict(self) -> dict:
        meta = super().metadata_dict()
        meta["contentType"] = self.content_type
        meta["sourceFormat"] = self.source_format
        if self.image_url:
            meta["imageUrl"] = self.image_url
        return meta


def chunk_document(
    markdown: str,
    *,
    business_id: str,
    source_url: str,
    category: str,
    source_format: str,
    doc_title: str,
) -> list[DocumentChunk]:
    """Markdown 全文 → 切片序列。doc_title 须由调用方给缺省(文件名词干),
    首个一级标题出现时升格覆盖为文档标题。"""
    chunks: list[DocumentChunk] = []
    header_stack: list[tuple[int, str]] = []  # (级别, 标题),级别 >3 收敛到 3(docling 可出 4-6 级)
    resolved_title = doc_title
    title_resolved = False

    def _current_header_path() -> str:
        if header_stack:
            return " > ".join(title for _, title in header_stack)
        return resolved_title  # 首个标题前的前置段落:挂文档标题,不静默丢

    def _emit(kind: str, text: str, image_url: str | None = None) -> None:
        if not text.strip():
            return
        chunks.append(
            DocumentChunk(
                business_id=business_id,
                source_url=source_url,
                doc_title=resolved_title,
                header_path=_current_header_path(),
                chunk_text=text.strip(),
                category=category,
                content_type=kind,
                image_url=image_url,
                source_format=source_format,
            )
        )

    plain: list[str] = []  # 待打包纯文本缓冲(保留空行作段落边界,交给 _split_blocks)

    def _flush_plain() -> None:
        if not plain:
            return
        blocks = _split_blocks("\n".join(plain).strip("\n"))
        plain.clear()
        for piece in _pack_blocks(blocks):
            _emit("text", piece)

    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        index += 1
        if not line.strip() or line.lstrip().startswith("<!--"):
            # 空行 = 段落边界保留进缓冲;docling 图片空壳占位(<!-- image -->)丢弃
            if plain and plain[-1] != "":
                plain.append("")
            continue

        header_match = _HEADER_RE.match(line)
        if header_match:
            _flush_plain()
            level = min(len(header_match.group(1)), 3)
            title = header_match.group(2).strip()
            if not title_resolved and len(header_match.group(1)) == 1:
                # 仅 `#` 级标题升格为文档标题(2026-10-17 对抗审查修复:此前任意层级
                # 首个标题都抢位 —— 全 Heading 2 文档里首个节标题会被误立为文档标题,
                # 同级兄弟节被错误嵌套为其子节;后到的真 # 又造成双根矛盾)。
                # 升格后强制压栈为 1 级:docling 把 Word Heading 1 映射为 ##、Title
                # 样式映射为 #,不强制则根标题会被同级节标题弹栈。无 # 的文档沿用
                # 调用方 doc_title(parse 的 #{1,2} 首标题或文件名词干),不做猜测。
                resolved_title, title_resolved = title, True
                header_stack.append((1, title))
                continue
            while header_stack and header_stack[-1][0] >= level:
                header_stack.pop()
            header_stack.append((level, title))
            continue

        image_match = _MD_IMAGE_LINE_RE.match(line.strip())
        if image_match:
            _flush_plain()
            caption = image_match.group(1).strip()
            _emit("image", f"文档插图:{caption or '未生成图片描述'}", image_url=image_match.group(2))
            continue

        if line.lstrip().startswith("|"):
            _flush_plain()
            rows = [line]
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index].rstrip())
                index += 1
            for table_piece in _split_table_chunks(rows):
                _emit("table", table_piece)
            continue

        if _HTML_TABLE_OPEN_RE.match(line.strip()):
            _flush_plain()
            first = line.strip()
            if "</table>" in first.lower():
                # 单行自闭合表:整行即一表,严禁向后续行吞并(2026-10-17 对抗审查:
                # 曾把其后的段落与下一张表的开行错标成表格块)
                _emit("table", first)
                continue
            rows = [line]
            while index < len(lines):
                probe = lines[index]
                if "</table>" in probe.lower():
                    rows.append(probe.rstrip())
                    index += 1
                    break
                if _HEADER_RE.match(probe.strip()):
                    break  # 未闭合表遇到标题行必须止步,严禁把文档剩余内容吞成一块
                rows.append(probe.rstrip())
                index += 1
            # HTML 退化表是罕见路径,不切行组,整块原样保留(结构信息 > 尺寸纪律)
            _emit("table", "\n".join(rows))
            continue

        plain.append(line)

    _flush_plain()
    return chunks


def _split_table_chunks(rows: list[str]) -> list[str]:
    """管道表 → 一或多个表格块:≤ 上限单块原样;超长按行组切成多个独立切片,
    每组重复表头行(词面锚点不因切分丢失)。"""
    table_text = "\n".join(rows)
    if len(table_text) <= TABLE_MAX_CHUNK_SIZE:
        return [table_text]

    # 表头 = 首行 + 分隔行(|---|);后续行组都带着它,词面锚点不丢
    header_rows = rows[:2] if len(rows) >= 2 and set(rows[1]) <= set("|-: ") else rows[:1]
    body_rows = rows[len(header_rows):]
    header_len = sum(len(r) + 1 for r in header_rows)
    groups: list[list[str]] = []
    buf: list[str] = []
    buf_len = header_len
    for row in body_rows:
        row_len = len(row) + 1
        if buf and buf_len + row_len > TABLE_MAX_CHUNK_SIZE:
            groups.append(buf)
            buf, buf_len = [], header_len
        buf.append(row)
        buf_len += row_len
    if buf:
        groups.append(buf)
    if not groups:
        # 表体行被表头耗尽(超长单行表/仅表头表):原样成单块。
        # 返回 [] 会让整张表静默消失,与「内容不丢」纪律直接矛盾
        # (2026-10-17 对抗审查实证,另须防 ingest 把空文档误诊为扫描件)。
        return [table_text]
    return ["\n".join(header_rows + group) for group in groups]
