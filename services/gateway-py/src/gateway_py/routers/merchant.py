"""商户门户服务端路由 — 移植 apps/merchant/app/{api,spi}/**/route.ts(18 条,路径与响应包 1:1)。

- /api/admin/*:商户运营台(会话接管、订单发货、HITL 审批)
- /api/store/*:门店前台(商品、地址、下单、AI 客服聊天 + SSE)
- /spi/v1/*:对外 SPI 合同(HMAC 可选签名,success/data/timestamp 信封)
- SSE 推送通道:Redis pub/sub 频道 ``thread:{threadId}:message``(替代 TS 进程内 agentEventEmitter)
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import time
import uuid as _uuid

from engine_py.approvals.gatekeeper import ApprovalGatekeeper
from engine_py.db import get_session
from engine_py.event_bus import get_client as get_redis
from engine_py.run_agent import AgentJobInput, run_agent
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import text

from .. import merchant_domain as mds
from ..conversation_repo import get_conversation_timeline, list_conversations
from ..hmac_signer import verify as hmac_verify

router = APIRouter()

THREAD_CHANNEL = "thread:{thread_id}:message"


def _err_msg(err: BaseException) -> str:
    return str(err)


def _ts_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# 商户注册门禁(A档,2026-09-04)
# ---------------------------------------------------------------------------


async def check_tenant_registered(business_id: str | None) -> JSONResponse | None:
    """校验客户端自报的 businessId/tenantId 已在 ``tenants`` 注册表登记且 ``status='active'``。

    背景:此前商户服务路径(门店聊天/会话读取/运营台)从不咨询注册表 —— 任意自报
    租户(实测 ghost-tenant-999)可获全套引擎服务,并以"X 官方商城"品牌扮演作出
    回复。本门禁仅约束商户路径;平台主站 ``/api/chat`` 通路不受限(内置租户
    ecommerce/nike/adidas 不走商户入驻)。

    返回 ``None`` = 放行;返回 ``JSONResponse`` = 调用方直接透出
    (403 未注册/已停用,503 注册表不可用 —— fail-closed:宁可拒绝服务,
    不可放行未注册租户)。"all" 为聚合视图参数,非单租户扮演,直接放行。
    """
    clean = (business_id or "").strip().lower()
    if clean == "all":
        return None
    try:
        async with get_session() as session:
            row = (
                await session.execute(
                    text("SELECT status FROM tenants WHERE LOWER(business_id) = :bid LIMIT 1"),
                    {"bid": clean},
                )
            ).first()
    except Exception as err:
        print(f"[TenantGate] tenants 注册表查询失败(fail-closed 拒绝请求): {err}")
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": "租户注册表暂不可用，请稍后重试"},
        )
    if row is None or str(row[0] or "").lower() != "active":
        print(f"[TenantGate] 拒绝未注册/已停用商户租户: {business_id!r}")
        return JSONResponse(
            status_code=403,
            content={"success": False, "error": f"商户 '{business_id}' 未入驻或已停用，请联系平台完成商户注册"},
        )
    return None


# ---------------------------------------------------------------------------
# SPI 鉴权 — 移植 apps/merchant/src/services/spiAuthGuard.ts
# ---------------------------------------------------------------------------


async def verify_spi_request(
    method: str,
    path: str,
    body: str,
    signature: str | None,
    timestamp: str | None,
    nonce: str | None,
    require_signature: bool = True,
) -> tuple[bool, str | None]:
    if not signature:
        if require_signature:
            return False, "Missing x-signature header for protected SPI endpoint"
        return True, None
    if not timestamp or not nonce:
        return False, "Missing x-timestamp or x-nonce headers for signed request"
    try:
        req_time = int(timestamp)
    except ValueError:
        return False, "Request timestamp expired (> 5 minutes window)"
    if abs(_ts_ms() - req_time) > 300000:
        return False, "Request timestamp expired (> 5 minutes window)"
    secret = os.environ.get("MERCHANT_API_SECRET") or os.environ.get("API_SECRET") or "aurora_secret_key_8899"
    ok = hmac_verify(secret, signature, method, path, timestamp, nonce, body)
    if not ok:
        return False, "Invalid HMAC-SHA256 signature"
    return True, None


# ---------------------------------------------------------------------------
# /api/admin — 商户运营台
# ---------------------------------------------------------------------------


@router.get("/api/admin/conversations")
async def admin_conversations(
    tenantId: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
):
    try:
        tenant_id = tenantId or "aurora"
        gate = await check_tenant_registered(tenant_id)
        if gate is not None:
            return gate
        res = await list_conversations(
            business_id=tenant_id,
            status=None if status == "all" else status,
            search_keyword=search,
            limit=50,
            offset=0,
        )
        conversations = [{**item, "id": item.get("threadId"), "lastMessage": item.get("lastMessageSnippet")} for item in (res.get("items") or [])]
        return {"success": True, "tenantId": tenant_id, "conversations": conversations, "total": res.get("total")}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.get("/api/admin/conversations/{thread_id}")
async def admin_conversation_detail(thread_id: str, tenantId: str | None = Query(None)):
    try:
        tenant_id = tenantId or "aurora"
        gate = await check_tenant_registered(tenant_id)
        if gate is not None:
            return gate
        timeline = await get_conversation_timeline(thread_id, tenant_id)
        now = _dt.datetime.now().isoformat()
        data = timeline or {
            "thread": {
                "threadId": thread_id,
                "businessId": tenant_id,
                "status": "active",
                "unreadCount": 0,
                "tags": [],
                "metadata": {},
                "createdAt": now,
                "updatedAt": now,
            },
            "messages": [],
        }
        return {"success": True, "data": data}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.get("/api/admin/orders")
async def admin_orders():
    try:
        data = await mds.get_admin_dashboard_data()
        return {"success": True, **data}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.post("/api/admin/orders/ship")
async def admin_orders_ship(body: dict):
    try:
        if not body.get("orderId") or not body.get("trackingNo"):
            return JSONResponse(
                status_code=400, content={"success": False, "message": "orderId and trackingNo are required"}
            )
        result = await mds.ship_order(
            body["orderId"], body.get("carrierCode") or "SF", body["trackingNo"]
        )
        return result
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "message": _err_msg(err)})


@router.get("/api/admin/approvals")
async def admin_approvals(
    tenantId: str | None = Query(None),
    status: str | None = Query(None),
    actionType: str | None = Query(None),
):
    try:
        tenant = tenantId or "aurora"
        gate = await check_tenant_registered(tenant)
        if gate is not None:
            return gate
        approvals = await ApprovalGatekeeper.list_pending_approvals(
            {
                "tenantId": None if tenant == "all" else tenant,
                "status": None if status == "all" else status,
                "actionType": None if actionType == "all" else actionType,
            }
        )
        return {"success": True, "approvals": approvals, "total": len(approvals)}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.post("/api/admin/approvals")
async def admin_approvals_action(body: dict):
    try:
        result = await ApprovalGatekeeper.process_approval_action(
            {
                "approvalId": body.get("approvalId"),
                "threadId": body.get("threadId"),
                "action": body.get("action"),
                "rejectionReason": body.get("rejectionReason"),
                "humanReply": body.get("humanReply") or body.get("replyMessage"),
                "isFinish": body.get("isFinish"),
            }
        )
        if result.get("error"):
            return JSONResponse(
                status_code=result.get("statusCode") or 400,
                content={"success": False, "error": result["error"]},
            )
        return {"success": True, **result}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


# ---------------------------------------------------------------------------
# /api/store — 门店前台
# ---------------------------------------------------------------------------


@router.get("/api/store/products")
async def store_products():
    try:
        products = await mds.search_products(limit=20)
        return {"success": True, "products": products}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.get("/api/store/products/{product_id}")
async def store_product_detail(product_id: str):
    try:
        product = await mds.get_product_detail(product_id)
        if product is None:
            return JSONResponse(
                status_code=404, content={"success": False, "error": f"商品 [{product_id}] 未找到或已下架"}
            )
        return {"success": True, "product": product}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.get("/api/store/addresses")
async def store_addresses(userId: str | None = Query(None)):
    try:
        addresses = await mds.get_customer_addresses(userId or "CUST-8801")
        return {"success": True, "addresses": addresses}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.post("/api/store/addresses")
async def store_save_address(body: dict):
    try:
        user_id = body.get("userId") or "CUST-8801"
        if not body.get("recipientName") or not body.get("phone"):
            return JSONResponse(
                status_code=400, content={"success": False, "error": "收货人姓名和手机号为必填项"}
            )
        result = await mds.save_customer_address(user_id, body)
        return result
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.get("/api/store/orders")
async def store_orders(
    customerId: str | None = Query(None),
    userId: str | None = Query(None),
    status: str | None = Query(None),
):
    try:
        uid = customerId or userId or "CUST-8801"
        orders = await mds.list_orders(
            {"userId": uid, "status": None if (status in (None, "ALL")) else status, "limit": 50}
        )
        return {"success": True, "orders": orders}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.post("/api/store/orders")
async def store_place_order(body: dict):
    try:
        customer_id = body.get("customerId") or "CUST-8801"

        if isinstance(body.get("items"), list) and body["items"]:
            shipping = body.get("shippingAddress")
            if isinstance(shipping, str):
                full_address = shipping
            else:
                full_address = (shipping or {}).get("fullAddress") or "北京市海淀区中关村南大街1号院8号楼1201室"
            result = await mds.create_order_from_cart(
                customer_id,
                body["items"],
                {
                    "recipientName": ((shipping or {}).get("recipientName") if isinstance(shipping, dict) else None)
                    or body.get("recipientName")
                    or "张伟",
                    "phone": ((shipping or {}).get("phone") if isinstance(shipping, dict) else None)
                    or body.get("recipientPhone")
                    or "13800138000",
                    "fullAddress": full_address,
                },
            )
            return result

        result = await mds.place_order(
            {
                "customerId": customer_id,
                "skuCode": body.get("skuCode"),
                "quantity": body.get("quantity") or 1,
                "shippingAddress": body.get("shippingAddress") or "北京市海淀区中关村南大街1号院8号楼1201室",
                "recipientName": body.get("recipientName") or "张伟",
                "recipientPhone": body.get("recipientPhone") or "13800138000",
            }
        )
        return result
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.get("/api/store/orders/{order_id}")
async def store_order_detail(order_id: str):
    try:
        order = await mds.get_order_detail(order_id)
        if order is None:
            return JSONResponse(status_code=404, content={"success": False, "error": f"未找到订单 [{order_id}]"})
        return {"success": True, "order": order}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


# ---------------------------------------------------------------------------
# /api/store/chat — AI 客服(同步 dispatch + Redis 频道推送 + SSE 流)
# ---------------------------------------------------------------------------


async def publish_thread_message(thread_id: str, payload: dict) -> None:
    try:
        client = await get_redis()
        if client is not None:
            await client.publish(THREAD_CHANNEL.format(thread_id=thread_id), json.dumps(payload, ensure_ascii=False))
    except Exception as err:
        print(f"[MerchantChat] Redis publish thread message failed: {err}")


@router.post("/api/store/chat")
async def store_chat(body: dict):
    try:
        effective_message = (body.get("message") or body.get("input") or "").strip()
        if not effective_message:
            return JSONResponse(status_code=400, content={"success": False, "error": "消息内容不能为空"})

        business_id = body.get("businessId") or "aurora"
        user_id = body.get("userId") or "CUST-8801"
        thread_id = body.get("threadId") or f"merchant_thread_{user_id}_{business_id}"
        job_id = f"job_{_ts_ms()}_{uuid4_hex(7)}"

        gate = await check_tenant_registered(business_id)
        if gate is not None:
            return gate

        final_state = await run_agent(
            AgentJobInput(
                jobId=job_id,
                threadId=thread_id,
                userId=user_id,
                businessId=business_id,
                message=effective_message,
            )
        )
        output = final_state.get("output") or final_state.get("result") or "极光潮品智能客服已为您处理完毕。"
        message_id = f"ast_{_ts_ms()}_{uuid4_hex(5)}"

        await publish_thread_message(
            thread_id,
            {
                "id": message_id,
                "role": "assistant",
                "content": output,
                "cards": final_state.get("cards") or [],
                "timestamp": _dt.datetime.now().isoformat(),
            },
        )

        return {
            "success": True,
            "messageId": message_id,
            "jobId": job_id,
            "threadId": thread_id,
            "userId": user_id,
            "output": output,
            "result": output,
            "cards": final_state.get("cards") or [],
        }
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


def uuid4_hex(n: int) -> str:
    raw = _uuid.uuid4().hex
    return raw[:n] if len(raw) >= n else raw


@router.get("/api/store/chat/messages")
async def store_chat_messages(
    request: Request,
    businessId: str | None = Query(None),
    tenantId: str | None = Query(None),
    threadId: str | None = Query(None),
    userId: str | None = Query(None),
    includeOlder: str | None = Query(None),
    allHistory: str | None = Query(None),
):
    try:
        tenant = businessId or tenantId or "aurora"
        gate = await check_tenant_registered(tenant)
        if gate is not None:
            return gate

        pg_user_id: str | None = None
        if userId:
            try:
                from engine_py.db.session import _engine

                async with _engine.connect() as conn:
                    row = (
                        await conn.execute(
                            text(
                                "SELECT id FROM users WHERE LOWER(email) = LOWER(:e) OR id = :u LIMIT 1"
                            ),
                            {"e": f"{userId}@example.com", "u": userId},
                        )
                    ).first()
                    if row:
                        pg_user_id = str(row[0])
            except Exception:
                pass

        list_res = await list_conversations(business_id=tenant, user_id=userId, limit=50, offset=0)

        def _belongs(item: dict) -> bool:
            if not userId:
                return False
            tid = item.get("threadId") or ""
            return bool(
                item.get("userId") == userId
                or (pg_user_id and item.get("userId") == pg_user_id)
                or f"_{userId}_" in tid
                or tid.endswith(f"_{userId}")
                or tid.startswith(userId)
            )

        user_threads = [item for item in (list_res.get("items") or []) if _belongs(item)]

        if not threadId and user_threads:
            active = next((t for t in user_threads if t.get("lastMessageSnippet")), None)
            threadId = (active or user_threads[0]).get("threadId")

        if not threadId:
            return {
                "success": True,
                "threadId": None,
                "thread": None,
                "messages": [],
                "userThreads": user_threads,
            }

        timeline = await get_conversation_timeline(threadId, tenant)

        include_older = includeOlder == "true" or allHistory == "true"
        all_historical_messages: list | None = None
        if include_older and user_threads:
            all_msgs: list[dict] = []
            for t in user_threads:
                tl = await get_conversation_timeline(t["threadId"], tenant)
                if tl and tl.get("messages"):
                    all_msgs.extend({**m, "threadId": t["threadId"]} for m in tl["messages"])

            def _ts_of(m: dict) -> float:
                raw = m.get("createdAt") or m.get("timestamp") or 0
                try:
                    # py3.11+ fromisoformat 已原生支持 "Z" 后缀,无需再替换
                    return _dt.datetime.fromisoformat(str(raw)).timestamp()
                except ValueError:
                    return 0.0

            all_msgs.sort(key=_ts_of)
            all_historical_messages = all_msgs

        return {
            "success": True,
            "threadId": threadId,
            "thread": (timeline or {}).get("thread"),
            "messages": (timeline or {}).get("messages") or [],
            "userThreads": user_threads,
            "allHistoricalMessages": all_historical_messages,
        }
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": _err_msg(err)})


@router.get("/api/store/chat/stream")
async def store_chat_stream(threadId: str | None = Query(None)):
    if not threadId:
        return Response("Missing threadId parameter", status_code=400)

    channel = THREAD_CHANNEL.format(thread_id=threadId)

    async def event_stream():
        yield f"event: connected\ndata: {json.dumps({'threadId': threadId, 'timestamp': _ts_ms()})}\n\n"
        pubsub = None
        client = None
        try:
            client = await get_redis()
            if client is not None:
                pubsub = client.pubsub()
                await pubsub.subscribe(channel)
        except Exception as err:
            print(f"[MerchantChatStream] Redis subscribe failed: {err}")

        try:
            while True:
                if pubsub is not None:
                    # 阻塞式等待(客户端 socket_timeout 需 > timeout,见 event_bus.get_client):
                    # 非阻塞轮询 + sleep 的写法会让每条消息延迟 15~30s 才转发——
                    # get_message(timeout=0) 首轮吞不掉已到达的消息,须下一轮才可见。
                    try:
                        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                    except (TimeoutError, RedisTimeoutError):
                        msg = None
                    if msg and msg.get("type") == "message":
                        data = msg.get("data")
                        if isinstance(data, bytes):
                            data = data.decode()
                        yield f"event: message\ndata: {data}\n\n"
                        continue
                else:
                    await asyncio.sleep(15.0)
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': _ts_ms()})}\n\n"
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# /spi/v1 — 对外 SPI 合同(HMAC 可选)
# ---------------------------------------------------------------------------


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
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"), require_signature=False,
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
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"), require_signature=False,
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
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"), require_signature=False,
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
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"), require_signature=False,
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
            request.headers.get("x-timestamp"), request.headers.get("x-nonce"), require_signature=True,
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
