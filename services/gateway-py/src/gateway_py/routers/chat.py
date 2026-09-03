"""Chat 路由 — 镜像 chat.controller/chat.service(dispatch + SSE 流 + messages + orders)。

SSE 直接消费 Phase 1a 事件主干(Redis Streams),与 TS pipeSSEFromStream 同一线协议:
``id: N`` 整数序号、Last-Event-ID 重放、15s 心跳、result 后 200ms 优雅关闭。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import text

from engine_py.db import get_session
from engine_py.event_bus import get_client, read_agent_events
from engine_py.run_agent import AgentJobInput, run_agent
from .. import conversation_repo

router = APIRouter(prefix="/api/chat")


class DispatchChatIn(BaseModel):
    message: str | None = None
    input: str | None = None
    threadId: str | None = None
    userId: str | None = None
    businessId: str | None = None
    imageUrls: list[str] | None = None
    sync: bool | None = None


@router.post("")
async def dispatch_chat(body: DispatchChatIn, request: Request):
    effective_message = (body.message or body.input or "").strip()
    if not effective_message:
        raise HTTPException(400, "Message is required")

    effective_thread_id = body.threadId or f"thread_{int(time.time() * 1000)}_{uuid.uuid4().hex[:5]}"
    effective_user_id = body.userId or "CUST-8801"
    tenant_header = request.headers.get("x-tenant-id") or request.headers.get("x-business-id")
    effective_business_id = body.businessId or tenant_header or "ecommerce"
    job_id = f"job_{int(time.time() * 1000)}_{uuid.uuid4().hex[:9]}"

    await conversation_repo.append_message(
        {
            "threadId": effective_thread_id,
            "businessId": effective_business_id,
            "userId": effective_user_id,
            "role": "user",
            "content": effective_message,
        }
    )

    job = AgentJobInput(
        jobId=job_id,
        threadId=effective_thread_id,
        userId=effective_user_id,
        businessId=effective_business_id,
        message=effective_message,
        imageUrls=body.imageUrls or [],
    )
    task = asyncio.create_task(run_agent(job))

    if body.sync:
        final_state = await task
        output = final_state.get("output") or "智能客服已为您处理完毕。"
        return {
            "success": True,
            "jobId": job_id,
            "threadId": effective_thread_id,
            "userId": effective_user_id,
            "output": output,
            "result": output,
            "cards": final_state.get("cards") or [],
            "isTemporalMode": False,
        }
    return {
        "success": True,
        "jobId": job_id,
        "threadId": effective_thread_id,
        "userId": effective_user_id,
        "isTemporalMode": False,
    }


async def _sse_frame(seq: int, event: str, data) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/{job_id}/stream")
async def sse_stream(job_id: str, request: Request, lastEventId: str | None = Query(None)):
    last_event_id_header = request.headers.get("last-event-id") or lastEventId
    last_seq = int(last_event_id_header) if last_event_id_header and last_event_id_header.isdigit() else 0

    async def frame_stream():
        yield ""  # 让响应头立刻落地
        client = await get_client()
        stream_key = f"job:events:{job_id}"
        last_entry_id = "0"
        history = await read_agent_events(job_id)
        finished = False
        for event in history:
            last_entry_id = event["entryId"]
            if event["seq"] > last_seq:
                yield await _sse_frame(event["seq"], event["type"], event["data"])
                if event["type"] == "result":
                    finished = True
        if finished:
            await asyncio.sleep(0.2)
            return

        while True:
            if await request.is_disconnected():
                return
            try:
                res = await client.xread({stream_key: last_entry_id}, count=50, block=15000)
            except RedisTimeoutError:
                # 客户端读超时先于 BLOCK 到期(redis-py socket_timeout 配置过小等):
                # 按一次轮询到期处理,发心跳续命而不是掐断整个流。
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': int(time.time() * 1000)})}\n\n"
                continue
            except Exception as err:  # noqa: BLE001 — 总线异常终止,客户端将带 Last-Event-ID 重连
                print(f"[ChatSSE] event bus read failed, closing stream: {err}")
                return
            if not res:
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': int(time.time() * 1000)})}\n\n"
                continue
            for _key, entries in res:
                for entry_id, fields in entries:
                    last_entry_id = entry_id
                    try:
                        seq = int(fields.get("seq", "0"))
                    except ValueError:
                        continue
                    event_type = fields.get("type", "")
                    try:
                        data = json.loads(fields.get("data", "null"))
                    except Exception:  # noqa: BLE001
                        data = fields.get("data")
                    yield await _sse_frame(seq, event_type, data)
                    if event_type == "result":
                        await asyncio.sleep(0.2)
                        return

    return StreamingResponse(
        frame_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/messages")
async def chat_messages(threadId: str | None = Query(None), businessId: str | None = Query(None)):
    if not threadId:
        return {"success": True, "messages": []}
    timeline = await conversation_repo.get_conversation_timeline(threadId, businessId)
    return {"success": True, "thread": timeline["thread"] if timeline else None, "messages": (timeline or {}).get("messages", [])}


@router.get("/orders")
async def chat_orders(userId: str = "CUST-8801", businessId: str = "ecommerce"):
    async with get_session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        'SELECT o.order_id, o.status, o.carrier, o.tracking_number, o.estimated_delivery, '
                        'o.total_amount, o.created_at, '
                        "COALESCE(o.recipient_name, ua.receiver_name) AS recipient_name, "
                        "COALESCE(o.phone, ua.receiver_phone) AS phone, "
                        "COALESCE(o.shipping_address, ua.full_address) AS full_address "
                        "FROM orders o LEFT JOIN user_addresses ua ON o.address_id = ua.id "
                        "WHERE o.business_id = :bid AND (o.user_id = :uid OR :uid = 'all') "
                        "ORDER BY o.created_at DESC LIMIT 20"
                    ).bindparams(bid=businessId.lower().strip(), uid=userId)
                )
            )
            .mappings()
            .all()
        )
    return {"success": True, "orders": [dict(r) for r in rows]}
