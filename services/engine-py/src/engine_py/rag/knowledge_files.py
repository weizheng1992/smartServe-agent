"""docs/knowledge Markdown 知识文档摄取 — 承接 TS 退役 updateRag.ts 的角色。

规格对齐 docs/rag-chunking-and-search.md §2(MarkdownChunker):
- frontmatter(title / businessId / category)声明归属租户,缺失 businessId 的文件整份跳过
  (多租户安全:绝不猜测归属);
- ``#``/``##``/``###`` 标题维护章节路径(headerPath = 各级标题 " > " 串联);
- SOP 有序列表(1. 2. 3.)原子不拆,超长章节按空行段落贪心打包(默认 ≤500 字符);
- 每个 (business_id, source_url=文件名) 下的切片可整体替换(替换语义见 seed/_ensure_seed_data)。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

MAX_CHUNK_SIZE = 500

_HEADER_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_ORDERED_LIST_RE = re.compile(r"^\d+[\.、]\s*")


@dataclass
class KnowledgeChunk:
    """一条知识切片:物理写入 rag_documents 的最小单元。"""

    business_id: str
    source_url: str  # 知识文件名(如 aurora_store_and_products.md),同文件切片整组替换的键
    doc_title: str
    header_path: str
    chunk_text: str
    category: str

    def contextual_summary(self) -> str:
        """确定性上下文摘要(Contextual Retrieval 的 [Context] 前缀段,零 LLM 调用)。"""
        return f"本段切片出自商户 [{self.business_id}] 的文档《{self.doc_title}》中「{self.header_path}」章节。"

    def embedding_input(self) -> str:
        return f"[Context] {self.contextual_summary()}\n\n[Content] {self.chunk_text}"

    def metadata_dict(self) -> dict:
        """rag_documents.metadata JSONB 统一组装口径(seed 与冷启动自愈共用)。"""
        return {
            "category": self.category,
            "docTitle": self.doc_title,
            "headerPath": self.header_path,
            "version": "1.0",
        }


def _parse_frontmatter(lines: list[str]) -> tuple[dict[str, str], int]:
    """解析 YAML 风格 frontmatter(仅支持平铺 key: value),返回 (元数据, 正文起始行号)。"""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta: dict[str, str] = {}
    for index in range(1, len(lines)):
        line = lines[index].strip()
        if line == "---":
            return meta, index + 1
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return {}, 0  # frontmatter 未闭合,按无元数据处理


def _split_blocks(section_text: str) -> list[str]:
    """按空行切段落;有序列表行(1. 2. …)与其后续缩进/续行粘连为原子块,保证 SOP 步骤不拆。"""
    blocks: list[str] = []
    current: list[str] = []
    in_list = False
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append("\n".join(current))
                current, in_list = [], False
            continue
        is_list_item = bool(_ORDERED_LIST_RE.match(stripped))
        if in_list and not is_list_item and not line.startswith((" ", "\t")):
            # 列表结束(回到普通段落),先封块再起新段
            blocks.append("\n".join(current))
            current = []
        current.append(line)
        in_list = is_list_item
    if current:
        blocks.append("\n".join(current))
    return blocks


def _pack_blocks(blocks: list[str]) -> list[str]:
    """贪心打包段落至 ≤ MAX_CHUNK_SIZE;单块自身超限则独立成块(不做句中硬切)。"""
    packed: list[str] = []
    buffer: list[str] = []
    buffer_len = 0
    for block in blocks:
        block_len = len(block)
        if buffer and buffer_len + block_len + 1 > MAX_CHUNK_SIZE:
            packed.append("\n\n".join(buffer))
            buffer, buffer_len = [], 0
        buffer.append(block)
        buffer_len += block_len
    if buffer:
        packed.append("\n\n".join(buffer))
    return packed


def parse_knowledge_file(path: Path) -> list[KnowledgeChunk]:
    """单文件解析:frontmatter 判归属,#/##/### 组章节路径,章节体切块。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    meta, body_start = _parse_frontmatter(lines)
    business_id = meta.get("businessId", "").strip()
    if not business_id:
        print(f"[KnowledgeFiles] 跳过缺少 businessId frontmatter 的文件: {path.name}")
        return []
    category = meta.get("category", "product_knowledge").strip() or "product_knowledge"
    source_url = path.name

    chunks: list[KnowledgeChunk] = []
    header_stack: list[tuple[int, str]] = []  # (级别, 标题),级别 1-3
    section_lines: list[str] = []

    def _flush_section() -> None:
        doc_title = next((title for level, title in header_stack if level == 1), source_url)
        header_path = " > ".join(title for _, title in header_stack)
        text = "\n".join(section_lines).strip()
        section_lines.clear()
        if not text or not header_path:
            return
        for piece in _pack_blocks(_split_blocks(text)):
            chunks.append(
                KnowledgeChunk(
                    business_id=business_id,
                    source_url=source_url,
                    doc_title=doc_title,
                    header_path=header_path,
                    chunk_text=piece,
                    category=category,
                )
            )

    for line in lines[body_start:]:
        header_match = _HEADER_RE.match(line)
        if header_match:
            level, title = len(header_match.group(1)), header_match.group(2).strip()
            _flush_section()
            # 弹出同级及更深的旧标题,维持路径栈
            while header_stack and header_stack[-1][0] >= level:
                header_stack.pop()
            header_stack.append((level, title))
        else:
            if header_stack:
                section_lines.append(line)
    _flush_section()
    return chunks


def default_knowledge_dir() -> Path:
    """知识目录:RAG_KNOWLEDGE_DIR 显式指定优先(容器部署 docs/ 不在仓库内时用),
    默认取仓库内 docs/knowledge(本模块位于 services/engine-py/src/engine_py/rag/,向上 5 级为仓库根)。"""
    override = os.environ.get("RAG_KNOWLEDGE_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[5] / "docs" / "knowledge"


def load_knowledge_chunks(directory: Path | None = None) -> list[KnowledgeChunk]:
    """扫描目录下全部 Markdown 知识文档(文件名排序,保证播种顺序确定)。"""
    target = directory or default_knowledge_dir()
    if not target.is_dir():
        print(f"[KnowledgeFiles] 知识目录不存在,跳过文件摄取: {target}")
        return []
    chunks: list[KnowledgeChunk] = []
    for path in sorted(target.glob("*.md")):
        chunks.extend(parse_knowledge_file(path))
    return chunks
