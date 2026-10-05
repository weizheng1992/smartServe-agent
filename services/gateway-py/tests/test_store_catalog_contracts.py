"""store 目录/地址面契约册(T7,2026-10-06 补零直接契约)。

此前 /api/store/products(列表/详情)与 /api/store/addresses(GET/POST)零
直接契约 —— 商城前台的目录浏览与地址薄全靠 e2e 间接覆盖。钉四组:列表形状
(独立用户种唯一编码,不串他套件)/ 详情 404 诚实文案 / 地址 GET 缺省行为 /
POST 必填校验 400 + 落库回读。
"""

from __future__ import annotations

import pytest

from gateway_py.merchant_db import ensure_merchant_tables

_UID = "CUST-CT-CAT-A"
_SPUCODE = "CT-CAT-SPU-1"
_SKUCODE = "CT-CAT-SKU-1"


async def _seed_one_product() -> None:
    await ensure_merchant_tables()
    from sqlalchemy import text

    from gateway_py.merchant_db import merchant_engine

    async with merchant_engine().begin() as conn:
        existing = (
            await conn.execute(text("SELECT 1 FROM merchant_skus WHERE sku_code = :c"), {"c": _SKUCODE})
        ).first()
        if existing is None:
            await conn.execute(
                text(
                    "INSERT INTO merchant_spus (spu_code, title, main_image) "
                    "VALUES (:sc, '目录契约测试冲锋衣', 'x.png')"
                ).bindparams(sc=_SPUCODE)
            )
            await conn.execute(
                text(
                    "INSERT INTO merchant_skus (spu_id, sku_code, sku_title, spec_attributes, price, stock) "
                    "SELECT p.id, :kc, '默认规格', CAST(:spec AS jsonb), 258, 10 "
                    "FROM merchant_spus p WHERE p.spu_code = :sc"
                ).bindparams(kc=_SKUCODE, spec='{"颜色":"黑"}', sc=_SPUCODE)
            )


@pytest.mark.usefixtures("seeded")
class TestStoreCatalogContracts:
    async def test_products_list_shape(self, client):
        await _seed_one_product()
        res = await client.get("/api/store/products")
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["products"], list)
        codes = [str(p.get("productId") or "") for p in body["products"]]  # productId = spu_code
        assert _SPUCODE in codes, f"种子商品应在目录中,实得前几项 {codes[:5]}"

    async def test_product_detail_200_and_honest_404(self, client):
        await _seed_one_product()
        listed = (await client.get("/api/store/products")).json()["products"]
        target = next(p for p in listed if str(p.get("productId") or "") == _SPUCODE)
        pid = str(target["productId"])

        detail = await client.get(f"/api/store/products/{pid}")
        assert detail.status_code == 200
        assert detail.json()["success"] is True

        missing = await client.get("/api/store/products/CT-CAT-NO-SUCH-SPU")
        assert missing.status_code == 404
        assert "未找到或已下架" in missing.json()["error"]

    async def test_addresses_get_returns_list(self, client):
        res = await client.get("/api/store/addresses", params={"userId": _UID})
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True
        assert isinstance(body["addresses"], list)

    async def test_addresses_post_validates_and_persists(self, client):
        bad = await client.post(
            "/api/store/addresses",
            json={"userId": _UID, "phone": "13800000000"},  # 缺收货人
        )
        assert bad.status_code == 400
        assert "必填" in bad.json()["error"]

        ok = await client.post(
            "/api/store/addresses",
            json={
                "userId": _UID,
                "recipientName": "目录契约收货人",
                "phone": "13800000001",
                "fullAddress": "契约市测试区 1 号",
            },
        )
        assert ok.status_code == 200

        listed = (await client.get("/api/store/addresses", params={"userId": _UID})).json()["addresses"]
        assert any(a.get("recipientName") == "目录契约收货人" for a in listed), f"落库后应可回读:{listed}"
