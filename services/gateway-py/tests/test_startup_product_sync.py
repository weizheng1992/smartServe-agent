"""启动商品知识同步的租户挂载回归(2026-09-25 帐篷幻觉实弹)。

症状:商户门户(businessId=aurora)问「几个帐篷的特点和价格对比」,客服
编造 3 款帐篷与价格(¥399/¥699/¥899)。真货架切片(极光帐篷 ¥1299/¥1499)
被启动钩子挂到演示租户 ecommerce 名下;aurora 检索被 rag_documents.
business_id 物理过滤,看不见自己的货架 → finish 零商品事实 → LLM 自由
发挥。本套钉死:启动同步的挂载身份必须是货架属主 _merchant_id(),
严禁硬编码/回退演示租户。
"""

from __future__ import annotations

import asyncio


def test_startup_sync_files_under_merchant_owner(monkeypatch):
    import engine_py.rag.product_knowledge as pk

    from gateway_py import main as gateway_main
    from gateway_py.merchant_domain import _merchant_id

    captured: dict = {}

    async def _captor(business_id: str) -> dict:
        captured["business_id"] = business_id
        return {"synced": 0, "skipped": True}

    # lifespan 内运行时 import,故 patch 源模块符号即对调用生效
    monkeypatch.setattr(pk, "sync_product_knowledge", _captor)
    asyncio.run(gateway_main._sync_product_knowledge_on_startup())
    assert captured.get("business_id") == _merchant_id(), (
        "启动商品知识同步必须挂载到货架属主租户(_merchant_id());"
        "挂到演示租户即 2026-09-25 帐篷幻觉病灶"
    )


def test_startup_sync_failure_never_blocks_lifespan(monkeypatch):
    """同步炸了只 print 不阻断启动(既有诚实跳过契约,搬迁后不回归)。"""
    import engine_py.rag.product_knowledge as pk

    from gateway_py import main as gateway_main

    async def _boom(business_id: str) -> dict:
        raise RuntimeError("merchant down")

    monkeypatch.setattr(pk, "sync_product_knowledge", _boom)
    asyncio.run(gateway_main._sync_product_knowledge_on_startup())  # 不抛即过
