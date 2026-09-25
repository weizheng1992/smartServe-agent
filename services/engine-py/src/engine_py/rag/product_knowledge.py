"""商品知识 RAG 同步(2026-09-13)—— 商户真货架派生,严禁编造假参数。

「极光 420g重磅毛圈棉抽绳束脚慢跑裤 特点」类商品知识问句此前落咨询直答
时 RAG 只有店铺政策、没有商品信息,诚实答「没找到」。本模块把商户真货架
(SPU title/subtitle/category/specs + SKU 规格/价格/库存)派生为每 SPU 一块
的知识切片写入 rag_documents,与 consult 直答共用同一检索链。

- 真数据红线:切片内容全部来自 merchant_spus/merchant_skus 真实字段,严禁
  从外部资料为虚构商品编造规格(real-data-only/01);品类级通用养护知识走
  docs/knowledge/ecommerce_product_knowledge.md 静态摄取,与本同步器互补。
- 幂等:source_url = product_catalog_sync.md 键下整组替换(与 knowledge_files
  的文件级替换语义一致);商户库不可达时诚实跳过,不阻塞启动。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from ..db import RagDocumentRow, get_session
from ..llm import get_embedding_model
from .knowledge_files import KnowledgeChunk

SYNC_SOURCE_URL = "product_catalog_sync.md"

_SPUS_SQL = (
    "SELECT s.id, s.spu_code, s.title, s.subtitle, s.description, s.category, s.specs, s.status "
    "FROM merchant_spus s WHERE s.status = 'ON_SALE' ORDER BY s.spu_code"
)
_SKUS_SQL = (
    "SELECT k.sku_title, k.price, k.stock, k.spec_attributes FROM merchant_skus k "
    "WHERE k.spu_id = CAST(:sid AS uuid) ORDER BY k.price, k.sku_code"
)


def _spec_line(specs: dict) -> str:
    parts = [f"{k}:{v}" for k, v in (specs or {}).items() if v]
    return "；".join(parts) if parts else ""


def build_product_chunks(rows: list[dict], business_id: str) -> list[KnowledgeChunk]:
    """SPU 行(含 skus 列表)→ 知识切片。纯函数,测试缝。"""
    chunks: list[KnowledgeChunk] = []
    for row in rows:
        title = row["title"]
        category = row["category"] or "商品"
        lines: list[str] = []
        if row.get("subtitle"):
            lines.append(f"商品卖点：{row['subtitle']}")
        if row.get("description") and row["description"] != row.get("subtitle"):
            lines.append(f"商品介绍：{row['description']}")
        spec = _spec_line(row.get("specs") or {})
        if spec:
            lines.append(f"核心规格：{spec}")
        skus = row.get("skus") or []
        if skus:
            variants = "；".join(
                f"{s.get('sku_title') or '默认规格'} ¥{s.get('price')}"
                for s in skus[:8]
            )
            lines.append(f"在售规格与价格：{variants}")
            prices = [float(s["price"]) for s in skus if s.get("price") is not None]
            total_stock = sum(int(s.get("stock") or 0) for s in skus)
            if prices:
                lines.append(f"价格区间：¥{min(prices)} ~ ¥{max(prices)}")
            lines.append(f"库存状态：{'现货充足' if total_stock > 20 else '现货'}（共 {total_stock} 件）")
        chunk = KnowledgeChunk(
            business_id=business_id,
            source_url=SYNC_SOURCE_URL,
            doc_title=f"商品知识：{title}",
            header_path=f"商品目录 > {category} > {title}",
            # 首行带商品名:chunk_text 是检索主字段,商品名缺席会让「XX 水壶怎么样」
            # 的名称语义落空,也使存量行无法按内容回填标题(admin-readiness 11)
            chunk_text="\n".join([f"商品名：{title}", *lines]) or title,
            category="product_knowledge",
        )
        chunks.append(chunk)
    return chunks


async def sync_product_knowledge(business_id: str) -> dict:
    """商户真货架 → rag_documents 商品知识切片(整组替换,幂等)。

    business_id 必显式传(2026-09-25 帐篷幻觉收口):租户挂载身份是调用方
    的决策,曾因默认 "ecommerce" + 网关硬编码,把 aurora 货架挂到演示租户
    名下 —— 属主检索看不见自己的商品,finish 零事实即编帐篷编价格。

    商户库不可达/无在售 SPU 时诚实跳过返回 {"synced": 0};嵌入失败同样
    中止(不留半同步状态)。每次调用全量重建该 source_url 键下内容 ——
    商户改标题/价格后网关重启即生效,30 SPU 级别开销秒级。
    """
    from ..tools_registry import order_domain

    try:
        engine = order_domain._merchant_reader_engine()
        async with engine.connect() as conn:
            spus = (await conn.execute(text(_SPUS_SQL))).mappings().all()
            rows: list[dict] = []
            for spu in spus:
                item = dict(spu)
                skus = (
                    await conn.execute(text(_SKUS_SQL).bindparams(sid=str(spu["id"])))
                ).mappings().all()
                item["skus"] = [dict(s) for s in skus]
                rows.append(item)
    except Exception as err:
        print(f"[ProductKnowledge] 商户货架不可达,跳过商品知识同步: {err}")
        return {"synced": 0, "skipped": True}

    chunks = build_product_chunks(rows, business_id)
    if not chunks:
        return {"synced": 0, "skipped": True}

    try:
        async with get_session() as session:
            await session.execute(
                text(
                    "DELETE FROM rag_documents WHERE business_id = :bid AND source_url = :src"
                ).bindparams(bid=business_id, src=SYNC_SOURCE_URL)
            )
            for chunk in chunks:
                embedding = await get_embedding_model().aembed_query(chunk.embedding_input())
                session.add(
                    RagDocumentRow(
                        business_id=chunk.business_id,
                        source_url=chunk.source_url,
                        chunk_text=chunk.chunk_text,
                        contextual_summary=chunk.contextual_summary(),
                        embedding=json.dumps(embedding),
                        metadata_=chunk.metadata_dict(),
                    )
                )
            await session.commit()
    except Exception as err:
        print(f"[ProductKnowledge] 商品知识写入失败(不留半同步状态): {err}")
        return {"synced": 0, "skipped": True}
    return {"synced": len(chunks)}
