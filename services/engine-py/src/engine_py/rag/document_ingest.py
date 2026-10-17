"""PDF/Word 文档批量摄取(document_ingest)— 文档 RAG 的编排层。

parse(双格式 → Markdown + 插图落盘)→ 字幕(插图 alt 补 VLM 描述,可降级)
→ chunk(表格原子块)→ 覆盖重建写入 rag_documents。写路径与
product_knowledge.py 同纪律:按 (business_id, source_url=文件名) 整组替换,
嵌入失败整体中止不留半同步状态;business_id 必显式传(租户挂载是调用方的
决策,缺省猜测曾把 aurora 货架挂到演示租户名下 —— 帐篷幻觉先例)。

与 knowledge_files 的关系:markdown 知识文件走检索侧自愈播种(contextual_rag
._ensure_seed_data),文档摄取没有自愈 —— 文档量大且解析重(docling 模型 +
VLM),自愈语义(每次检索指纹比对)不适用;摄取入口只有本模块的 CLI 与
gateway 上传端点,失败诚实返回,不静默。

CLI:
    uv run --env-file .env python -m engine_py.rag.document_ingest <文件或目录> \
        --business-id aurora [--category document] [--no-vlm]
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from ..db import RagDocumentRow, get_session
from ..llm import get_embedding_model
from .document_chunker import DocumentChunk, chunk_document
from .document_parse import DocumentParseError, parse_document, uploads_root

DEFAULT_CATEGORY = "document"

_SUPPORTED_SUFFIXES = {".pdf", ".docx", ".doc"}  # .doc 摄取时报诚实错误(见 document_parse)

_CAPTION_PROMPT = (
    "用中文客观描述这张文档插图:一句话说明它是什么,若是图表请概述关键数据与趋势。"
    "只描述图中真实存在的内容,严禁编造图中没有的信息,不超过两句话。"
)

_ALT_ESCAPE_RE = re.compile(r"[\\[\]\n\r]")  # 反斜杠一并净化:字幕进 alt 行,转义序列(\1 \U C:\Users)无意义且危险
# 每文档字幕上限(2026-10-17 对抗审查):20MB 上限不约束张数,数千张 2KB 小图的
# docx 若无闸可换数百次串行 glm-4.6v 付费调用与分钟级请求占位;超限插图诚实降级
_MAX_CAPTIONS_PER_DOC = 20


@dataclass
class DocumentIngestResult:
    """单文件摄取结果(CLI 汇总与 gateway 响应共用形状)。"""

    file: str
    status: str  # ingested | skipped | failed
    chunks: int = 0
    tables: int = 0
    images: int = 0
    captioned: int = 0
    doc_title: str | None = None
    partial: bool = False  # docling PARTIAL_SUCCESS:部分页失败,内容不完整
    reason: str | None = None


def vlm_caption_enabled() -> bool:
    """VLM 字幕开关(RAG_DOC_VLM_CAPTION=0 关):批量离线导入可关,省视觉调用;
    关闭或失败时图片字幕降级为「未生成图片描述」,检索靠所在章节标题兜底。"""
    return os.environ.get("RAG_DOC_VLM_CAPTION", "1") != "0"


async def ingest_document_file(
    path: Path,
    business_id: str,
    *,
    category: str = DEFAULT_CATEGORY,
    caption_images: bool = True,
    source_url: str | None = None,
) -> DocumentIngestResult:
    """单文档摄取:解析 → 字幕 → 切块 → 覆盖重建。失败返回 status=failed
    (含诚实 reason),绝不抛出中断批量流程;参数非法(缺租户)才 raise。"""
    business_id = (business_id or "").strip()
    if not business_id:
        raise ValueError("ingest_document_file 缺少 business_id:文档归属租户必须显式指定,严禁缺省猜测")
    source_url = source_url or path.name
    result = DocumentIngestResult(file=path.name, status="failed")

    try:
        parsed = await asyncio.to_thread(parse_document, path)
    except DocumentParseError as err:
        result.reason = str(err)
        return result
    except Exception as err:  # docling 内部异常(损坏文件等)诚实落 failed
        result.reason = f"文档解析异常: {err}"
        print(f"[DocIngest] {path.name} 解析异常: {err}")
        return result

    markdown = parsed.markdown
    if caption_images and vlm_caption_enabled() and parsed.image_urls:
        for url in parsed.image_urls:
            if result.captioned >= _MAX_CAPTIONS_PER_DOC:
                print(
                    f"[DocIngest] {path.name}: 插图字幕达每文档上限 {_MAX_CAPTIONS_PER_DOC},"
                    f"其余 {len(parsed.image_urls) - result.captioned} 张降级无描述"
                )
                break
            caption = await _vlm_caption(url)
            if caption:
                try:
                    markdown = _apply_caption(markdown, url, caption)
                except Exception as err:  # 单图字幕改写失败降级,不中断整份摄取(诚实律:响亮降级)
                    print(f"[DocIngest] {path.name} 字幕改写失败,该图降级无描述({url}): {err}")
                    continue
                result.captioned += 1
    elif parsed.image_urls:
        print(f"[DocIngest] {path.name}: {len(parsed.image_urls)} 张插图跳过 VLM 字幕(开关关闭)")

    chunks = chunk_document(
        markdown,
        business_id=business_id,
        source_url=source_url,
        category=category,
        source_format=parsed.source_format,
        doc_title=parsed.doc_title or path.stem,
    )
    if not chunks:
        result.status = "skipped"
        result.reason = "未提取到任何内容(扫描件无文本层或空文档);OCR 支持为 v2 裁决项"
        return result

    try:
        written = await _replace_document_chunks(business_id, chunks)
    except Exception as err:
        result.reason = f"切片写入失败(不留半同步状态): {err}"
        print(f"[DocIngest] {path.name} 写入失败: {err}")
        return result

    result.status = "ingested"
    result.chunks = written
    result.tables = sum(1 for c in chunks if c.content_type == "table")
    result.images = sum(1 for c in chunks if c.content_type == "image")
    result.doc_title = parsed.doc_title or path.stem
    result.partial = parsed.partial
    print(
        f"[DocIngest] {path.name} 摄取成功: {written} 切片"
        f"(表格 {result.tables} / 插图 {result.images},VLM 字幕 {result.captioned})"
        + (";⚠️ 文档部分页转换失败(partial),内容不完整" if parsed.partial else "")
    )
    return result


async def ingest_document_directory(
    directory: Path,
    business_id: str,
    *,
    category: str = DEFAULT_CATEGORY,
    caption_images: bool = True,
) -> list[DocumentIngestResult]:
    """目录批量摄取(文件名排序保证顺序确定);目录不存在诚实空列表。"""
    if not directory.is_dir():
        print(f"[DocIngest] 目录不存在,零摄取: {directory}")
        return []
    targets = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES)
    if not targets:
        print(f"[DocIngest] 目录内无 pdf/docx/doc 文件,零摄取: {directory}")
        return []
    results: list[DocumentIngestResult] = []
    for path in targets:
        results.append(await ingest_document_file(path, business_id, category=category, caption_images=caption_images))
    return results


async def _replace_document_chunks(business_id: str, chunks: list[DocumentChunk]) -> int:
    """(business_id, source_url) 键下整组替换;嵌入失败整体中止,不留半同步状态。

    事务级 advisory lock 串行化同名并发摄取(2026-10-17 对抗审查实证):
    DELETE→逐条 embed→commit 的窗口内,第二次同名上传的 DELETE 看不见未提交
    快照会照常放行,终态新旧两版并存且无收敛机制 —— 先取 (business_id,
    source_url) 的事务锁,后到者阻塞至前序提交,其 DELETE 再清掉前序版本。
    """
    async with get_session() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))").bindparams(
                lock_key=f"{business_id}:{chunks[0].source_url}"
            )
        )
        await session.execute(
            text("DELETE FROM rag_documents WHERE business_id = :bid AND source_url = :src").bindparams(
                bid=business_id, src=chunks[0].source_url
            )
        )
        rows: list[RagDocumentRow] = []
        for chunk in chunks:
            embedding = await get_embedding_model().aembed_query(chunk.embedding_input())
            rows.append(
                RagDocumentRow(
                    business_id=chunk.business_id,
                    source_url=chunk.source_url,
                    chunk_text=chunk.chunk_text,
                    contextual_summary=chunk.contextual_summary(),
                    embedding=json.dumps(embedding),
                    metadata_=chunk.metadata_dict(),
                )
            )
        session.add_all(rows)
        await session.commit()
        return len(rows)


def _apply_caption(markdown: str, url: str, caption: str) -> str:
    r"""把指定图片引用的 alt 改写为字幕(字幕净化掉会破坏 markdown 语法的字符)。

    替换必须走**函数替换**而非字符串模板:re.sub 的替换串里 `\1` 是组引用、
    `\U`/`\n` 是转义 —— VLM 字幕回显正则/LaTeX/Windows 路径时必然炸或静默换行。
    """
    clean = _ALT_ESCAPE_RE.sub(" ", caption).strip()[:300]
    return re.sub(
        rf"!\[[^\]]*\]\({re.escape(url)}\)",
        lambda _match: f"![{clean}]({url})",
        markdown,
    )


async def _vlm_caption(image_url: str) -> str | None:
    """插图字幕:glm-4.6v 单图描述;失败降级 None(切片落「未生成图片描述」)。
    视觉失败域独立(vision 同纪律),不入全局熔断。"""
    from langchain_core.messages import HumanMessage

    from ..llm import get_vision_model

    local_path = uploads_root() / image_url.removeprefix("/api/uploads/")
    if not local_path.is_file():
        print(f"[DocIngest] 插图文件缺失,跳过字幕: {image_url}")
        return None
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(local_path.suffix.lower(), "image/png")
    data_url = f"data:{mime};base64,{base64.b64encode(local_path.read_bytes()).decode()}"
    try:
        response = await get_vision_model().ainvoke(
            [
                HumanMessage(
                    content=[
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": _CAPTION_PROMPT},
                    ]
                )
            ]
        )
        content = response.content
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        caption = (content or "").strip()
        return caption or None
    except Exception as err:
        print(f"[DocIngest] 插图字幕生成失败,降级无描述({image_url}): {err}")
        return None


def _print_summary(results: list[DocumentIngestResult]) -> int:
    """CLI 汇总输出;返回退出码(任一 failed 即 1 —— 批量失败必须可被脚本感知)。"""
    ingested = sum(1 for r in results if r.status == "ingested")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")
    for r in results:
        mark = {"ingested": "✅", "skipped": "⏭️", "failed": "❌"}.get(r.status, "·")
        detail = f" {r.chunks} 切片(表 {r.tables}/图 {r.images})" if r.status == "ingested" else ""
        print(f"  {mark} {r.file}{detail}" + (f" — {r.reason}" if r.reason else ""))
    print(f"[DocIngest] 完成:成功 {ingested} / 跳过 {skipped} / 失败 {failed}")
    return 1 if failed else 0


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="批量摄取 PDF/Word 文档入 RAG(rag_documents;表格原子块 + 插图 VLM 字幕)"
    )
    parser.add_argument("path", help="文档文件(.pdf/.docx)或目录")
    parser.add_argument("--business-id", required=True, help="归属租户 businessId(必显式,严禁缺省猜测)")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help=f"切片分类标签(默认 {DEFAULT_CATEGORY})")
    parser.add_argument("--no-vlm", action="store_true", help="跳过 VLM 图片字幕(纯离线批量省视觉调用)")
    args = parser.parse_args()

    path = Path(args.path).expanduser()
    caption_images = not args.no_vlm

    async def _run() -> int:
        if path.is_dir():
            results = await ingest_document_directory(path, args.business_id, category=args.category, caption_images=caption_images)
        elif path.is_file():
            results = [await ingest_document_file(path, args.business_id, category=args.category, caption_images=caption_images)]
        else:
            print(f"[DocIngest] 路径不存在: {path}")
            return 1
        return _print_summary(results)

    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    _main()
