"""促销前台路由租户契约(2026-10-14 夜评深查第二处 🔴 收口):/api/store/promotions
三路由此前零租户过滤 —— fetch_active_promos 全表裸查 + 路由连 businessId 参数
都未收,跨租户活动前台可见可用(结算活动分支由引擎层同批闸死)。

修后:三路由收 businessId(缺省 aurora,与 store_place_order 单店部署口径同律),
引擎层 resolve_business_id 三段式兜底,租户谓词无条件携带。
"""

from __future__ import annotations

import uuid as _uuid

import pytest
from sqlalchemy import text

from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine

_TAG = "PROMO-TN"
_PRICE = 500.0


async def _seed_activity(business_id: str, name: str, discount: float) -> str:
    promo_id = str(_uuid.uuid4())
    async with merchant_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO promotions (id, business_id, name, promo_type, status, discount_value, "
                "threshold_amount, scope_type) "
                "VALUES (CAST(:i AS uuid), :b, :n, 'full_reduction', 'active', :v, :t, 'all')"
            ).bindparams(i=promo_id, b=business_id, n=name, v=discount, t=_PRICE)
        )
    return promo_id


async def _cleanup() -> None:
    async with merchant_engine().begin() as conn:
        await conn.execute(text("DELETE FROM promotions WHERE name LIKE :p").bindparams(p=f"{_TAG}%"))


@pytest.fixture(autouse=True)
async def _seed_two_tenants():
    await ensure_merchant_tables()
    await _seed_activity("aurora", f"{_TAG}-AURORA", 50.0)
    await _seed_activity("nike", f"{_TAG}-NIKE", 80.0)
    yield
    await _cleanup()


class TestStorePromotionsTenantScope:
    async def test_promotions_list_scoped_by_tenant(self, client):
        """缺省(单店口径 aurora)只见本店活动;显式 businessId=nike 只见 nike。"""
        default_view = (await client.get("/api/store/promotions")).json()["promotions"]
        names = {p["name"] for p in default_view}
        assert f"{_TAG}-AURORA" in names, f"缺省视图须含本店活动: {names}"
        assert f"{_TAG}-NIKE" not in names, "跨租户活动严禁进缺省促销列表"

        nike_view = (await client.get("/api/store/promotions", params={"businessId": "nike"})).json()["promotions"]
        nike_names = {p["name"] for p in nike_view}
        assert nike_names == {f"{_TAG}-NIKE"}, f"nike 视图只含 nike 活动: {nike_names}"

    async def test_promo_prices_batch_scoped_by_tenant(self, client):
        """批量促销价按租户取活动集:nike 视图吃 nike 满500减80,缺省视图吃 aurora。"""
        items = [{"productId": "PROMO-TN-SPU", "price": _PRICE}]

        nike_res = (await client.post("/api/store/promotions/prices", json=items,
                                      params={"businessId": "nike"})).json()["prices"]
        assert float(nike_res[0]["promoPrice"]) == 420.0, f"nike 视图应吃满500减80: {nike_res}"
        assert f"{_TAG}-NIKE" in (nike_res[0]["promoName"] or "")

        default_res = (await client.post("/api/store/promotions/prices", json=items)).json()["prices"]
        assert float(default_res[0]["promoPrice"]) == 450.0, f"缺省视图应吃 aurora 满500减50: {default_res}"
        assert f"{_TAG}-AURORA" in (default_res[0]["promoName"] or "")

    async def test_promo_price_single_scoped_by_tenant(self, client):
        """单商品促销价同律:缺省视图不吃他租活动。"""
        res = (await client.get("/api/store/promotions/price",
                                params={"productId": "PROMO-TN-SPU", "price": _PRICE})).json()
        assert res["promoName"] is not None and f"{_TAG}-AURORA" in res["promoName"]
        assert float(res["promoPrice"]) == 450.0
