"""商城促销/领券前台(/api/store/promotions*、/api/store/coupons*)—— 自
merchant.py 拆出(2026-10-15 夜评拆缝:merchant.py 双超 900 行,促销段是
天然拆缝)。服务端唯一算价,避免前端规则漂移;租户口径缺省 aurora(单店
部署口径,与下单/券包路由同律)。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/store/promotions")
async def store_promotions(businessId: str | None = Query(None)):
    """在售活动列表(商城首页/商品页展示;仅 active 且未过期,租户内)。

    businessId 缺省 aurora(单店部署口径,与下方下单/券包路由同律);
    2026-10-14 夜评:此前零租户过滤,跨租户活动前台可见可用。"""
    from engine_py.analytics.promotion_engine import fetch_active_promos
    from engine_py.tools_registry.order_domain import merchant_reader_engine

    async with merchant_reader_engine().connect() as conn:
        promos = await fetch_active_promos(conn, businessId or "aurora")
    return {
        "success": True,
        "promotions": [
            {"id": p["id"], "name": p["name"], "promoType": p["promo_type"],
             "threshold": float(p["threshold_amount"]) if p["threshold_amount"] is not None else None,
             "value": float(p["discount_value"]), "scopeType": p["scope_type"], "scopeValue": p["scope_value"]}
            for p in promos
        ],
    }


@router.get("/api/store/promotions/price")
async def store_promo_price(productId: str = Query(...), price: float = Query(...),
                            businessId: str | None = Query(None)):
    """单商品促销价(划线价展示;无可用活动返回原价;租户内,同上)。"""
    from engine_py.analytics.promotion_engine import promo_for_spu
    from engine_py.tools_registry.order_domain import merchant_reader_engine

    async with merchant_reader_engine().connect() as conn:
        promo = await promo_for_spu(conn, productId, price, businessId or "aurora")
    if not promo:
        return {"success": True, "originalPrice": price, "promoPrice": price, "promoName": None}
    return {"success": True, "originalPrice": price, "promoPrice": promo["promoPrice"], "promoName": promo["name"]}


@router.post("/api/store/promotions/prices")
async def store_promo_prices_batch(items: list[dict], businessId: str | None = Query(None)):
    """批量促销价(商城商品列表;服务端唯一算价,避免前端规则漂移;租户内,同上)。

    活动集整批一次拉取后内存打分 —— 不逐商品重查活动(此前 200 商品 =
    200 次活动全量 SELECT,2026-09-27 夜审 F3)。"""
    from engine_py.analytics.promotion_engine import promo_prices_batch
    from engine_py.tools_registry.order_domain import merchant_reader_engine

    sliced = items[:200]
    async with merchant_reader_engine().connect() as conn:
        bests = await promo_prices_batch(
            conn, [(str(i.get("productId")), float(i.get("price") or 0)) for i in sliced],
            businessId or "aurora",
        )
    out = []
    for item, promo in zip(sliced, bests):
        out.append({
            "productId": item.get("productId"),
            "originalPrice": float(item.get("price") or 0),
            "promoPrice": promo["promoPrice"] if promo else float(item.get("price") or 0),
            "promoName": promo["name"] if promo else None,
        })
    return {"success": True, "prices": out}


@router.get("/api/store/promotions/by-order")
async def store_promo_by_order(orderId: str = Query(...)):
    """订单优惠关联(商城订单展示原价/优惠/实付)。"""
    from engine_py.tools_registry.order_domain import merchant_reader_engine
    from sqlalchemy import text as _t

    async with merchant_reader_engine().connect() as conn:
        row = (
            await conn.execute(_t(
                "SELECT p.name AS promo_name, r.discount_amount AS discount, p.promo_type "
                "FROM promotion_redemptions r JOIN promotions p ON p.id = r.promotion_id "
                "WHERE r.order_id = :oid LIMIT 1"
            ).bindparams(oid=orderId))
        ).mappings().first()
    if not row:
        return {"success": True, "applied": False}
    return {"success": True, "applied": True, "promoName": row["promo_name"],
            "discount": float(row["discount"]), "promoType": row["promo_type"]}


@router.post("/api/store/coupons/claim")
async def store_claim_coupon(request: Request):
    body = await request.json()
    promo_id = str(body.get("promoId") or "")
    user_id = str(body.get("userId") or "").strip()
    if not promo_id or not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "promoId/userId 必传"})
    from engine_py.analytics import promotions as P

    result = await P.claim_coupon(promo_id, user_id, business_id=str(body.get("businessId") or "aurora"))
    if "error" in result:
        return JSONResponse(status_code=400, content={"success": False, **result})
    return {"success": True, **result}


@router.get("/api/store/coupons")
async def store_my_coupons(request: Request, userId: str = Query(...), businessId: str = Query("aurora")):
    from engine_py.analytics import promotions as P

    coupons = await P.my_coupons(userId, businessId)
    return {"success": True, "coupons": coupons}
