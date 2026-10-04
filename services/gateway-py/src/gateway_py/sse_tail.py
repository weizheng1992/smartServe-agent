"""SSE 读流深模块 — 事件主干消费端唯一泵(架构审查 #3,2026-10-04)。

XREAD 尾随、心跳、Last-Event-ID 回放、断连检查、坏 seq 跳过、JSON 回落、
终局收口等九组读流机制此前在 chat(`/api/chat/{jobId}/stream`)、analytics
ask(`/api/admin/analytics/ask`)、merchant store(`/api/store/chat/stream`)
三份手抄,回放策略已实际分叉(chat 历史回放 / ask 内联 seq 过滤 / store
pub/sub 断线即漏)。本 module 把读流收成一个 interface,Stream 与 pub/sub
是缝上的两个 adapter:

- ``tail_stream``:Redis Streams 读流。历史回放(``read_agent_events``,只补
  seq > last_seq)→ 尾随(XREAD BLOCK);终局事件在历史中即优雅收口不进轮询;
  ``__done__`` 类哨兵可判收口而不出 SSE 线(客户端未知事件掉兜底渲染,不外泄);
  可选兜底死线(生产者意外死亡时以 error 帧收口,期间心跳续命不误杀)。
- ``tail_pubsub``:Redis pub/sub 读流(顾客侧实时频道;天然无回放,断线丢帧
  由上层时间线拉取兜底),带 connected 首帧、心跳与断连检查。
- ``streaming_headers``:SSE StreamingResponse 头块的唯一形状(CORS 可选)。

测试桩点唯一:monkeypatch 本 module 的 ``get_client`` / ``read_agent_events``
(此前三路由各持一份私有绑定,逐副本 patch)。线格式与既有契约逐字节一致:
``id: {seq}\\nevent: {type}\\ndata: {json}\\n\\n``、心跳 ``event: heartbeat\\n...``。
"""

from __future__ import annotations

import asyncio
import json
import time
import typing

from engine_py.event_bus import get_client, read_agent_events, stream_key
from redis.exceptions import TimeoutError as RedisTimeoutError

__all__ = ["get_client", "read_agent_events", "streaming_headers", "tail_pubsub", "tail_stream"]


def _sse_frame(seq: int, event: str, data) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _sse_line(event: str, data) -> str:
    """无 id 帧(心跳/哨兵级错误帧)。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _heartbeat() -> str:
    return _sse_line("heartbeat", {"timestamp": int(time.time() * 1000)})


def streaming_headers(*, cors: bool = False, extra: dict | None = None) -> dict:
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    if cors:
        headers["Access-Control-Allow-Origin"] = "*"
    if extra:
        headers.update(extra)
    return headers


async def tail_stream(
    job_id: str,
    *,
    last_seq: int = 0,
    disconnected: typing.Callable[[], typing.Awaitable[bool]] | None = None,
    stop_on: frozenset[str] = frozenset({"result"}),
    emit_stop: bool = True,
    stop_grace: float = 0.2,
    deadline_seconds: float | None = None,
    deadline_frame: tuple[str, dict] | None = None,
    error_prefix: str = "SseTail",
):
    """Streams 读流泵:历史回放 → 尾随,终局收口。

    - 回放:``read_agent_events`` 全量历史只补 seq > last_seq;终局事件已在
      历史中 → 发完即优雅收口,绝不进 XREAD 轮询。
    - 尾随:心跳续命(RedisTimeout 先于 BLOCK 到期 / 空轮询)、断连即停、
      坏 seq 跳过、JSON 解析失败回落原文。
    - 终局:``stop_on`` 命中即收口;``emit_stop=False`` 的哨兵(如 ask 的
      ``__done__``)只判收口不出线。
    - 死线:``deadline_seconds`` 到点以 ``deadline_frame`` 收口(生产者意外
      死亡的消费端兜底;None = 不设死线,chat 语义)。
    """
    client = await get_client()
    yield ""  # 让响应头立刻落地
    stream = stream_key(job_id)
    last_entry_id = "0"

    # ---- 历史回放(断线重连只补缺失帧,不重算) ----
    # 哨兵抑制在回放路径同样生效:生产者已终结的流,重连补完缺失帧后即收口,
    # 哨兵本身不出 SSE 线(emit_stop=False 语义,与尾随路径一致)。
    history = await read_agent_events(job_id)
    for event in history:
        last_entry_id = event["entryId"]
        if event["type"] in stop_on and not emit_stop:
            return
        if event["seq"] > last_seq:
            yield _sse_frame(event["seq"], event["type"], event["data"])
            if event["type"] in stop_on:
                if stop_grace:
                    await asyncio.sleep(stop_grace)
                return

    # ---- 尾随 ----
    loop = asyncio.get_event_loop()
    deadline = (loop.time() + deadline_seconds) if deadline_seconds is not None else None
    while True:
        if disconnected is not None and await disconnected():
            return
        if deadline is not None and loop.time() > deadline:
            yield _sse_line(*(deadline_frame or ("error", {"message": "stream deadline exceeded"})))
            return
        try:
            res = await client.xread({stream: last_entry_id}, count=50, block=15000)
        except RedisTimeoutError:
            # 客户端读超时先于 BLOCK 到期(redis-py socket_timeout 配置过小等):
            # 按一次轮询到期处理,发心跳续命而不是掐断整个流。
            yield _heartbeat()
            continue
        except Exception as err:
            print(f"[{error_prefix}] event bus read failed, closing stream: {err}")
            return
        if not res:
            yield _heartbeat()
            continue
        for _key, entries in res:
            for entry_id, fields in entries:
                last_entry_id = entry_id
                event_type = fields.get("type", "")
                if event_type in stop_on and not emit_stop:
                    return
                try:
                    seq = int(fields.get("seq", "0"))
                except ValueError:
                    continue
                try:
                    data = json.loads(fields.get("data", "null"))
                except Exception:
                    data = fields.get("data")
                yield _sse_frame(seq, event_type, data)
                if event_type in stop_on:
                    if stop_grace:
                        await asyncio.sleep(stop_grace)
                    return


async def tail_pubsub(
    channel: str,
    *,
    connected_payload: dict | None = None,
    disconnected: typing.Callable[[], typing.Awaitable[bool]] | None = None,
    idle_seconds: float = 15.0,
):
    """pub/sub 读流泵(顾客侧实时频道 thread:{id}:message)。

    阻塞式等待(socket_timeout 需 > idle_seconds):非阻塞轮询 + sleep 的写法
    会让每条消息延迟 15~30s 才转发 —— get_message(timeout=0) 首轮吞不掉已到达
    的消息,须下一轮才可见。pub/sub 天然无回放,断线期间消息由上层时间线拉取兜底。
    """
    yield ""  # 让响应头立刻落地
    if connected_payload is not None:
        yield _sse_line("connected", connected_payload)
    pubsub = None
    client = None
    try:
        client = await get_client()
        if client is not None:
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
    except Exception as err:
        print(f"[SseTail] pubsub subscribe failed: {err}")

    try:
        while True:
            if disconnected is not None and await disconnected():
                return
            if pubsub is not None:
                try:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=idle_seconds)
                except (TimeoutError, RedisTimeoutError):
                    msg = None
                if msg and msg.get("type") == "message":
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode()
                    yield f"event: message\ndata: {data}\n\n"
                    continue
            else:
                await asyncio.sleep(idle_seconds)
            yield _heartbeat()
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass
