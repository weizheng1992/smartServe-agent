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

# 发布四步(INCR → XADD → 2×EXPIRE)打包为单次往返的 Lua 脚本。不能简单
# pipeline:XADD fields 里的 seq 取自同脚本 INCR 的返回值(线格式冻结,消费端
# 按 fields.seq 断点续传),纯 pipeline 在入队时拿不到该结果。每帧 4 次串行
# RTT → 1 次;SSE 高频帧下显著省时。两 key 带 {jobId} 同 hash tag,cluster
# 下也落同槽。
_PUBLISH_LUA = """
local seq = redis.call('INCR', KEYS[2])
redis.call('XADD', KEYS[1], 'MAXLEN', '~', ARGV[1], '*', 'seq', tostring(seq),
           'type', ARGV[2], 'data', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('EXPIRE', KEYS[2], ARGV[4])
return seq
"""

_client: aioredis.Redis | None = None


def stream_key(job_id: str) -> str:
    """作业事件流 key 的唯一真源(公开导出):网关 SSE 消费端(gateway_py
    routers/chat.py、analytics.py)须经此处取 key,严禁再手写字面量副本 ——
    格式一改 SSE 即静默断流(夜审 2026-09-29 收口)。"""
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
        seq = await client.eval(
            _PUBLISH_LUA,
            2,
            stream_key(job_id),
            _seq_key(job_id),
            STREAM_MAXLEN,  # ARGV[1]: MAXLEN ~ 上限
            event_type,  # ARGV[2]
            json.dumps(data if data is not None else None, ensure_ascii=False),  # ARGV[3]
            STREAM_TTL_SECONDS,  # ARGV[4]: 两 key TTL
        )
        return int(seq)
    except Exception:
        return None


async def read_agent_events(job_id: str) -> list[dict]:
    """读取 job 事件流全部历史条目(SSE 断线重连按 Last-Event-ID 回放用)。"""
    client = await get_client()
    try:
        entries = await client.xrange(stream_key(job_id), min="-", max="+")
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
