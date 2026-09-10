"""Chat 路由 — 镜像 chat.controller/chat.service(dispatch + SSE 流 + messages + orders)。

SSE 直接消费 Phase 1a 事件主干(Redis Streams),与 TS pipeSSEFromStream 同一线协议:
``id: N`` 整数序号、Last-Event-ID 重放、15s 心跳、result 后 200ms 优雅关闭。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

from engine_py.db import get_session
from engine_py.event_bus import get_client, read_agent_events
from engine_py.onboarding import build_entry_cards, resolve_onboarding_config
from engine_py.run_agent import AgentJobInput, run_agent
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy import text

from .. import conversation_repo

router = APIRouter(prefix="/api/chat")

# ---- 图片上传(wayfinder multimodal-image-chat 002)----
# 白名单 MIME → 扩展名:不信任客户端文件名,扩展名由服务端从 MIME 反推,
# UUID 命名落盘天然免疫路径穿越(文件名不含任何客户端可控成分)
_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 256 * 1024

# 默认仓库根 public/uploads(TS 原版同址,已在 .gitignore);env 可覆写(测试隔离用)
UPLOADS_DIR = Path(
    os.environ.get("UPLOADS_DIR")
    or (Path(__file__).resolve().parents[5] / "public" / "uploads")
)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload")
async def upload_chat_image(file: UploadFile = File(...)):  # noqa: B008 — FastAPI 依赖注入惯用法
    """接收聊天图片,UUID 落盘本地 uploads 目录,回 /api/uploads/ 静态 URL。

    前端契约(ChatArea.tsx):成功顶层 {success, url} 直接入 attachedImages;
    失败顶层 {success: false, error} 供 alert 精确展示。大小以读流实测为准,
    不信任 client 声明的 Content-Length。
    """
    ext = _ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if ext is None:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": f"不支持的图片类型 {file.content_type or '(未知)'},仅限 jpeg/png/webp/gif",
            },
        )
    dest = UPLOADS_DIR / f"{uuid.uuid4().hex}{ext}"
    try:
        with dest.open("wb") as out:
            written = 0
            while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    out.close()
                    dest.unlink(missing_ok=True)
                    return JSONResponse(
                        status_code=413,
                        content={"success": False, "error": "图片超过 10MB 上限"},
                    )
                out.write(chunk)
    finally:
        await file.close()
    return {"success": True, "url": f"/api/uploads/{dest.name}"}


class DispatchChatIn(BaseModel):
    message: str | None = None
    input: str | None = None
    threadId: str | None = None
    userId: str | None = None
    businessId: str | None = None
    imageUrls: list[str] | None = None
    sync: bool | None = None


def _generate_thread_id() -> str:
    """客户端未带 threadId 时的服务端生成器(dispatch 与显式建线程共用同一形状)。"""
    return f"thread_{int(time.time() * 1000)}_{uuid.uuid4().hex[:5]}"


@router.post("")
async def dispatch_chat(body: DispatchChatIn, request: Request):
    effective_message = (body.message or body.input or "").strip()
    if not effective_message:
        raise HTTPException(400, "Message is required")

    effective_thread_id = body.threadId or _generate_thread_id()
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
            "imageUrls": body.imageUrls,
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


def _greeting_row(
    thread_id: str,
    business_id: str,
    user_id: str,
    message_id: str,
    content: str,
    cards: list | None = None,
) -> dict:
    """首访 welcome 行与回访 greet 行的共形载荷(仅 cards 有无之差)。"""
    row = {
        "threadId": thread_id,
        "businessId": business_id,
        "userId": user_id,
        "id": message_id,
        "role": "assistant",
        "content": content,
    }
    if cards:
        row["cards"] = cards
    return row


class CreateThreadIn(BaseModel):
    threadId: str | None = None
    userId: str | None = None
    businessId: str | None = None


@router.get("/threads")
async def list_chat_threads(
    userId: str = Query(...),
    businessId: str | None = Query(None),
):
    """终端顾客会话列表(new-user-onboarding B,路由计数 42→43)。

    TS 基线无此路由,web 侧栏 fetchThreads 长期吞 404 恒空 —— 同一个缺口
    也挡住了服务端权威首访判定。契约:必填 ``userId``(严格属主等值过滤,
    防跨用户泄漏),可选 ``businessId`` 收窄,``updated_at DESC``;服务端
    固定封顶 50,不对客户端开放翻页参数。
    """
    threads = await conversation_repo.list_user_threads(
        user_id=userId,
        business_id=businessId,
        limit=50,
    )
    return {"success": True, "threads": threads}


@router.post("/threads")
async def create_chat_thread(body: CreateThreadIn, request: Request):
    """建线程(web「开启新一轮对话」前置)。TS 基线服务端缺失此路由,前端
    静默吞 404 导致按钮长期失效 —— wayfinder 004 E2E 钉出后补齐。幂等可重放;
    同 id 异主(他租户/他用户)冲突返回 409,绝不回显他人线程元数据。

    new-user-onboarding C:新建线程即落引导 assistant 行 —— 该用户在该租户的
    首线程给全量引导(welcomeText + 能力入口 quick_replies 卡),回访新线程给
    一行轻问候;消息 id 确定性(``welcome_/greet_ + threadId``)+ 仅真新建时写,
    幂等重放零重复。"""
    thread_id = body.threadId or _generate_thread_id()
    tenant_header = request.headers.get("x-tenant-id") or request.headers.get("x-business-id")
    business_id = (body.businessId or tenant_header or "ecommerce").lower().strip()
    thread = await conversation_repo.create_thread(
        thread_id=thread_id,
        business_id=business_id,
        user_id=body.userId,
    )
    if thread is None:
        raise HTTPException(409, "Thread ID conflicts with an existing thread under another owner")

    if thread.get("created"):
        # 引导行必须归属真实用户:首访判定按 user×tenant,匿名线程(body
        # 与既有行皆无 userId)无从判定,不落引导行、不冒认演示账号身份。
        effective_user_id = body.userId or thread.get("userId")
        if effective_user_id:
            prior_threads = await conversation_repo.list_user_threads(
                user_id=effective_user_id, business_id=business_id, limit=2
            )
            is_first_thread = len(prior_threads) <= 1  # 仅本次新建的这一条
            try:
                onboarding = await resolve_onboarding_config(business_id)
                if is_first_thread:
                    await conversation_repo.append_message(
                        _greeting_row(
                            thread_id,
                            business_id,
                            effective_user_id,
                            f"welcome_{thread_id}",  # 确定性 id:重放天然幂等
                            onboarding["welcomeText"],
                            cards=build_entry_cards(onboarding),
                        )
                    )
                else:
                    await conversation_repo.append_message(
                        _greeting_row(
                            thread_id,
                            business_id,
                            effective_user_id,
                            f"greet_{thread_id}",
                            onboarding["returningGreeting"],
                        )
                    )
            except Exception as greet_err:
                # 引导行失败不阻断建线程主契约(线程已建好,聊天照常可用)
                print(f"[ChatThreads] Failed to persist onboarding greeting for {thread_id}: {greet_err}")

    return {"success": True, "thread": thread}


@router.delete("/threads")
async def delete_chat_thread(threadId: str = Query(...), userId: str = Query(...)):
    """删除会话线程(web 侧栏删线程按钮,TS 时代调用至今服务端恒 405 ——
    2026-09-10 补齐存量缺口,路由计数 43→44)。

    契约:``threadId``/``userId`` 必填(缺参 422);属主不符或线程无属主
    返回 403(顾客列表严格等值本就看不到无主线程);查无此线程 404;成功
    同事务删除消息、task_memory 挂起任务态与线程行。审计类记录(审批/
    意图留痕/遥测)刻意保留 —— 审批与遥测是平台审计资产,不随顾客删线程蒸发。
    """
    outcome = await conversation_repo.delete_thread(threadId, userId)
    if outcome == "not_found":
        raise HTTPException(404, "Thread not found")
    if outcome == "forbidden":
        raise HTTPException(403, "Thread does not belong to the requesting user")
    return {"success": True, "threadId": threadId}


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
            except Exception as err:
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
                    except Exception:
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
