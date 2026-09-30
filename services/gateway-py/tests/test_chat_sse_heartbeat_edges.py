"""聊天 SSE 流边缘分支专册(2026-10-01 夜审补缺;此前 96 契约只钉主链路)。

钉死 `routers/chat.py::sse_stream` 的五条边缘语义:
1. Last-Event-ID:非数字回落 0(全量重放)、数字增量重放、header 优先于 query;
2. 历史含 result → 优雅关闭,绝不进轮询;
3. RedisTimeoutError(客户端读超时先于 BLOCK 到期)→ 心跳续命而非掐流;
4. 空轮询 → 心跳;
5. 事件总线读失败 → 响亮关流(打印 + 终止);坏 seq 字段条目跳过不炸流。

协作方(get_client / read_agent_events)全部 monkeypatch,零真 Redis。
无 result 的事件流永不自行终止,重放用例一律以一条 result 活动条目收流。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from gateway_py.routers import chat as chat_router


class _FakeRequest:
    def __init__(self, last_event_id: str | None = None):
        self.headers = {"last-event-id": last_event_id} if last_event_id else {}

    async def is_disconnected(self) -> bool:
        return False


class _FakeClient:
    """按脚本逐轮回放 xread 结果;异常项抛出;脚本耗尽视为流已无事可读(抛
    RuntimeError 触发「关流」分支,防重放用例无 result 终点而空转)。"""

    def __init__(self, polls: list):
        self.polls = list(polls)
        self.xread_calls = 0

    async def xread(self, streams, count=None, block=None):
        self.xread_calls += 1
        if not self.polls:
            raise RuntimeError("polls exhausted(测试脚本缺 result 终点)")
        item = self.polls.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _live_entry(entry_id: str, seq: int, event_type: str, data: dict) -> tuple:
    return (entry_id, {"seq": str(seq), "type": event_type, "data": json.dumps(data, ensure_ascii=False)})


def _poll(*entries: tuple) -> list:
    """xread 真实返回形:[(stream_key, [(entry_id, fields), ...]), ...]。"""
    return [("job:events:job-1", list(entries))]


def _history(*events: tuple[int, str, dict]) -> list[dict]:
    return [
        {"entryId": f"{seq}-1", "seq": seq, "type": etype, "data": data}
        for seq, etype, data in events
    ]


@pytest.fixture()
def wire_event_bus(monkeypatch):
    """接线桩:可编程历史与轮询脚本;返回 (install, client_holder)。"""
    holder: dict = {}

    def install(history: list[dict], polls: list) -> _FakeClient:
        client = _FakeClient(polls)
        holder["client"] = client

        async def _get_client():
            return client

        async def _read_history(job_id):
            return list(history)

        monkeypatch.setattr(chat_router, "get_client", _get_client)
        monkeypatch.setattr(chat_router, "read_agent_events", _read_history)
        return client

    return install


async def _collect(endpoint_result) -> list[str]:
    frames = []
    async for chunk in endpoint_result.body_iterator:
        if chunk:
            frames.append(chunk)
    return frames


def test_非数字LastEventId回落全量重放(wire_event_bus):
    history = _history((1, "status", {"n": 1}), (2, "status", {"n": 2}))
    wire_event_bus(history, polls=[_poll(_live_entry("9-1", 9, "status", {"n": 9})), _poll(_live_entry("10-1", 10, "result", {"ok": True}))])
    resp = asyncio.run(chat_router.sse_stream("job-1", _FakeRequest(), lastEventId="abc"))
    frames = asyncio.run(_collect(resp))
    assert frames == [
        'id: 1\nevent: status\ndata: {"n": 1}\n\n',
        'id: 2\nevent: status\ndata: {"n": 2}\n\n',
        'id: 9\nevent: status\ndata: {"n": 9}\n\n',
        'id: 10\nevent: result\ndata: {"ok": true}\n\n',
    ]


def test_数字LastEventId增量重放(wire_event_bus):
    history = _history((1, "status", {"n": 1}), (2, "status", {"n": 2}))
    wire_event_bus(history, polls=[_poll(_live_entry("10-1", 10, "result", {"ok": True}))])
    resp = asyncio.run(chat_router.sse_stream("job-1", _FakeRequest(), lastEventId="1"))
    frames = asyncio.run(_collect(resp))
    assert frames == [
        'id: 2\nevent: status\ndata: {"n": 2}\n\n',
        'id: 10\nevent: result\ndata: {"ok": true}\n\n',
    ]


def test_header优先于query(wire_event_bus):
    history = _history((1, "status", {"n": 1}), (2, "status", {"n": 2}), (3, "status", {"n": 3}))
    wire_event_bus(history, polls=[_poll(_live_entry("10-1", 10, "result", {"ok": True}))])
    req = _FakeRequest(last_event_id="1")  # header
    resp = asyncio.run(chat_router.sse_stream("job-1", req, lastEventId="3"))  # query 次之
    frames = asyncio.run(_collect(resp))
    assert [f.split("\n")[0] for f in frames] == ["id: 2", "id: 3", "id: 10"]


def test_历史含result优雅关闭不进轮询(wire_event_bus):
    history = _history((1, "status", {"n": 1}), (2, "result", {"ok": True}))
    client = wire_event_bus(history, polls=[Exception("不应进入轮询")])
    resp = asyncio.run(chat_router.sse_stream("job-1", _FakeRequest(), lastEventId=None))
    frames = asyncio.run(_collect(resp))
    assert [f.split("\n")[1] for f in frames] == ["event: status", "event: result"]
    assert client.xread_calls == 0, "历史已完结,不得进入 xread 轮询"


def test_RedisTimeout发心跳续命(wire_event_bus):
    polls = [
        RedisTimeoutError("socket read timed out"),
        _poll(_live_entry("10-1", 10, "result", {"ok": True})),
    ]
    client = wire_event_bus([], polls=polls)
    resp = asyncio.run(chat_router.sse_stream("job-1", _FakeRequest(), lastEventId=None))
    frames = asyncio.run(_collect(resp))
    assert frames[0].startswith("event: heartbeat\ndata: "), "读超时先于 BLOCK 到期 → 心跳续命而非掐流"
    assert "\nid:" not in frames[0]
    assert frames[-1].split("\n")[1] == "event: result"
    assert client.polls == [], "超时后必须 continue 下一轮,不得终止流"


def test_空轮询发心跳(wire_event_bus):
    polls = [[], _poll(_live_entry("10-1", 10, "result", {"ok": True}))]
    wire_event_bus([], polls=polls)
    resp = asyncio.run(chat_router.sse_stream("job-1", _FakeRequest(), lastEventId=None))
    frames = asyncio.run(_collect(resp))
    assert frames[0].startswith("event: heartbeat\ndata: ")
    assert frames[-1].split("\n")[1] == "event: result"


def test_事件总线读失败响亮关流(wire_event_bus, capsys):
    wire_event_bus([], polls=[RuntimeError("connection reset")])
    resp = asyncio.run(chat_router.sse_stream("job-1", _FakeRequest(), lastEventId=None))
    frames = asyncio.run(_collect(resp))
    assert frames == [], "通用异常 → 关流,不发心跳"
    assert "event bus read failed" in capsys.readouterr().out


def test_坏seq字段条目跳过不炸流(wire_event_bus):
    polls = [_poll(
        ("11-1", {"seq": "not-a-number", "type": "status", "data": "{}"}),
        _live_entry("11-2", 11, "result", {"ok": True}),
    )]
    wire_event_bus([], polls=polls)
    resp = asyncio.run(chat_router.sse_stream("job-1", _FakeRequest(), lastEventId=None))
    frames = asyncio.run(_collect(resp))
    assert [f.split("\n")[0] for f in frames] == ["id: 11"]
