"""对外 SPI 合同面(/spi/v1/*,HMAC 强制)—— 自 merchant.py 拆出(2026-10-15
夜评拆缝:merchant.py 双超 900 行,促销段/SPI 段是天然拆缝)。

五路由(search/user/orders-list/orders-detail/orders-action)信封 success/data/
timestamp;验签 fail-closed(2026-10-02 收免签名放行 + 2026-10-14 收源码兜底
密钥 —— 无签名恒拒,env 双缺拒绝验签,详见 verify_spi_request)。
限流:spi 作用域挂本面前缀 /spi/v1(rate_limit._RATE_SCOPES)。
"""

from __future__ import annotations

import json
import os

from engine_py.event_bus import get_client as get_redis
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from .. import merchant_domain as mds
from ..hmac_signer import verify as hmac_verify
from .merchant import _err_msg, _ts_ms

router = APIRouter()


async def verify_spi_request(
    method: str,
    path: str,
    body: str,
    signature: str | None,
    timestamp: str | None,
    nonce: str | None,
) -> tuple[bool, str | None]:
    """SPI 合同面 HMAC 验签(fail-closed,2026-10-14 夜评 🟡 收口):
    - 无签名恒拒绝(免签名后门参数已删除 —— 五调用点此前全显式 True,参数
      是纯逃逸面);
    - 密钥只认 env(MERCHANT_API_SECRET > API_SECRET),源码兜底密钥
      aurora_secret_key_8899 删除 —— 密钥进源码即进 git 史,拿着仓库即可
      伪造签名;env 双缺时拒绝并响亮留痕,生产在 .env 配置。"""
    if not signature:
        return False, "Missing x-signature header for protected SPI endpoint"
    if not timestamp or not nonce:
        return False, "Missing x-timestamp or x-nonce headers for signed request"
    try:
        req_time = int(timestamp)
    except ValueError:
        return False, "Request timestamp expired (> 5 minutes window)"
    if abs(_ts_ms() - req_time) > 300000:
        return False, "Request timestamp expired (> 5 minutes window)"
    secret = os.environ.get("MERCHANT_API_SECRET") or os.environ.get("API_SECRET")
    if not secret:
        print(
            "[SPI] HMAC 密钥未配置(MERCHANT_API_SECRET/API_SECRET 均缺),fail-closed 拒绝验签 —— "
            "生产/联调环境须在 .env 配置密钥"
        )
        return False, "SPI secret not configured (set MERCHANT_API_SECRET)"
    ok = hmac_verify(secret, signature, method, path, timestamp, nonce, body)
    if not ok:
        return False, "Invalid HMAC-SHA256 signature"
    # nonce 防重放(2026-10-02 code-review:此前 nonce 收而不查重,同一签名
    # 300s 窗口内可无限重放 —— tools-registry §1.2「防重放」从此完整兑现)。
    # Redis 不可用 fail-open(与 rate_limit 同一取向),不阻断正常签名流。
    try:
        client = await get_redis()
        if client is not None:
            if not await client.set(f"spi:nonce:{nonce}", "1", nx=True, ex=300):
                return False, "Replayed nonce (anti-replay window 300s)"
    except Exception as err:
        print(f"[SPI] nonce 防重放 Redis 不可用,fail-open: {err}")
    return True, None


@router.get("/spi/v1/products/search")
async def spi_products_search(
    request: Request,
    query: str | None = Query(None),
    category: str | None = Query(None),
    limit: str | None = Query(None),
):
    try:
        ok, error = await verify_spi_request(
            request.method, request.url.path, "", request.headers.get("x-signature"),
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"),
        )
        if not ok:
            return JSONResponse(status_code=401, content={"success": False, "message": error})
        products = await mds.search_products(
            query=query or None, category=category or None, limit=int(limit) if limit else 10
        )
        return {"success": True, "data": products, "timestamp": _ts_ms()}
    except Exception as err:
        print(f"[SPI] GET /spi/v1/products/search failed: {err}")
        return JSONResponse(status_code=500, content={"success": False, "message": _err_msg(err)})


@router.get("/spi/v1/user/info")
async def spi_user_info(request: Request, userId: str | None = Query(None), userEmail: str | None = Query(None)):
    try:
        ok, error = await verify_spi_request(
            request.method, request.url.path, "", request.headers.get("x-signature"),
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"),
        )
        if not ok:
            return JSONResponse(status_code=401, content={"success": False, "message": error})
        user = await mds.get_user_info({"userId": userId, "userEmail": userEmail})
        return {"success": True, "data": user, "timestamp": _ts_ms()}
    except Exception as err:
        print(f"[SPI] GET /spi/v1/user/info failed: {err}")
        return JSONResponse(status_code=500, content={"success": False, "message": _err_msg(err)})


@router.get("/spi/v1/orders/list")
async def spi_orders_list(
    request: Request,
    userId: str | None = Query(None),
    status: str | None = Query(None),
    limit: str | None = Query(None),
):
    try:
        ok, error = await verify_spi_request(
            request.method, request.url.path, "", request.headers.get("x-signature"),
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"),
        )
        if not ok:
            return JSONResponse(status_code=401, content={"success": False, "message": error})
        orders = await mds.list_orders(
            {"userId": userId or None, "status": status or None, "limit": int(limit) if limit else 10}
        )
        return {"success": True, "data": orders, "timestamp": _ts_ms()}
    except Exception as err:
        print(f"[SPI] GET /spi/v1/orders/list failed: {err}")
        return JSONResponse(status_code=500, content={"success": False, "message": _err_msg(err)})


@router.get("/spi/v1/orders/detail")
async def spi_orders_detail(request: Request, orderId: str | None = Query(None)):
    try:
        ok, error = await verify_spi_request(
            request.method, request.url.path, "", request.headers.get("x-signature"),
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"),
        )
        if not ok:
            return JSONResponse(status_code=401, content={"success": False, "message": error})
        if not orderId:
            return JSONResponse(status_code=400, content={"success": False, "message": "orderId is required"})
        order = await mds.get_order_detail(orderId)
        if order is None:
            return JSONResponse(
                status_code=404, content={"success": False, "message": f"Order {orderId} not found"}
            )
        return {"success": True, "data": order, "timestamp": _ts_ms()}
    except Exception as err:
        print(f"[SPI] GET /spi/v1/orders/detail failed: {err}")
        return JSONResponse(status_code=500, content={"success": False, "message": _err_msg(err)})


@router.post("/spi/v1/orders/action")
async def spi_orders_action(request: Request):
    try:
        raw_body = (await request.body()).decode()
        signature = request.headers.get("x-signature") or ""

        ok, error = await verify_spi_request(
            request.method, request.url.path, raw_body, signature,
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"),
        )
        if not ok:
            return JSONResponse(status_code=401, content={"success": False, "message": error})

        payload = json.loads(raw_body)
        if not payload.get("orderId") or not payload.get("actionType"):
            return JSONResponse(
                status_code=400, content={"success": False, "message": "orderId and actionType are required"}
            )

        result = await mds.execute_order_action(payload, signature)
        return {"success": result.get("success"), "data": result, "timestamp": _ts_ms()}
    except Exception as err:
        print(f"[SPI] POST /spi/v1/orders/action failed: {err}")
        return JSONResponse(status_code=500, content={"success": False, "message": _err_msg(err)})
