"""Agent 事件总线(Redis Streams)— 与 packages/tools/src/eventBus.ts 线格式逐字节兼容。

契约(README「与 TS 侧的互操作契约」):
- stream key ``job:events:{jobId}`` / seq key ``job:seq:{jobId}``
- entry fields:``seq``(十进制字符串)、``type``、``data``(JSON 字符串)
- ``XADD MAXLEN ~ 200``,两 key 均带 600s TTL
- JSON 序列化 ``ensure_ascii=False``,与 TS ``JSON.stringify`` 字节一致
- 发布失败静默降级(返回 None),不阻断执行 —— 与 TS 侧行为一致
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from .config import settings

STREAM_MAXLEN = 200
STREAM_TTL_SECONDS = 600

_client: aioredis.Redis | None = None


def _stream_key(job_id: str) -> str:
    return f"job:events:{job_id}"


def _seq_key(job_id: str) -> str:
    return f"job:seq:{job_id}"


async def get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        # redis-py asyncio 默认 socket_timeout=5(redis/_defaults.py),而 SSE 消费端
        # XREAD BLOCK 15000 会让服务端挂起 15s —— 客户端 5s 先炸 TimeoutError,
        # 网关 SSE 就会在空闲 5s 后静默断流。读超时必须 > 最大 BLOCK 时长(+ 余量)。
        _client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=20)
    return _client


async def publish_agent_event(job_id: str, event_type: str, data: Any) -> int | None:
    """发布一条 job 级事件,返回分配的 seq;失败静默返回 None。"""
    client = await get_client()
    try:
        seq = await client.incr(_seq_key(job_id))
        await client.xadd(
            _stream_key(job_id),
            {
                "seq": str(seq),
                "type": event_type,
                "data": json.dumps(data if data is not None else None, ensure_ascii=False),
            },
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
        await client.expire(_stream_key(job_id), STREAM_TTL_SECONDS)
        await client.expire(_seq_key(job_id), STREAM_TTL_SECONDS)
        return seq
    except Exception:
        return None


async def read_agent_events(job_id: str) -> list[dict]:
    """读取 job 事件流全部历史条目(SSE 断线重连按 Last-Event-ID 回放用)。"""
    client = await get_client()
    try:
        entries = await client.xrange(_stream_key(job_id), min="-", max="+")
    except Exception:
        return []
    events: list[dict] = []
    for entry_id, fields in entries:
        try:
            seq = int(fields.get("seq", "0"))
        except ValueError:
            continue
        try:
            data = json.loads(fields.get("data", "null"))
        except Exception:
            data = fields.get("data")
        events.append({"entryId": entry_id, "seq": seq, "type": fields.get("type", ""), "data": data})
    return events


async def emit(job_id: str, event: str, payload: Any) -> None:
    """按 TS 侧 eventEmitter.mirrorToEventBus 的语义发布:
    ``result`` 事件携带非空 cards 时,先发 ``cards``(独立 seq)再发 ``result``。
    """
    if event == "result" and isinstance(payload, dict):
        cards = payload.get("cards")
        if isinstance(cards, list) and len(cards) > 0:
            await publish_agent_event(job_id, "cards", {"cards": cards})
    await publish_agent_event(job_id, event, payload)


async def emit_status(job_id: str, message: str, node: str = "triage", plan: Any = None) -> None:
    """镜像名称空间事件 ``${jobId}:status`` 词汇:{status, node, message, plan?}。"""
    payload: dict[str, Any] = {"status": "executing", "node": node, "message": message}
    if plan is not None:
        payload["plan"] = plan
    await publish_agent_event(job_id, "status", payload)


async def emit_job_result(job_id: str, output: str, task_plan: Any = None, cards: Any = None) -> None:
    """镜像名称空间事件 ``${jobId}:result`` 词汇:{output, taskPlan, cards}(不拆 cards)。"""
    await publish_agent_event(
        job_id,
        "result",
        {"output": output, "taskPlan": task_plan, "cards": cards},
    )
