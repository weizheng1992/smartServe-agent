"""Data agent ask SSE 断线回放契约(2026-09-26 夜审 A6 收口)。

ask 流此前是内联直排:客户端断线即丢整轮答案,重试 = 重算。收口后与 chat
``/api/chat/{jobId}/stream`` 同一事件源架构 —— 帧落 Redis Streams(event_bus
契约),首连响应头 ``X-Ask-Id``,重连带 ``Last-Event-ID`` 只补发剩余帧,
**不重算**(计算挂后台任务,断开不停算)。
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from gateway_py.main import app

pytestmark = pytest.mark.usefixtures("seeded")

TENANT = {"x-tenant-id": "aurora"}


def _sse_frames(resp) -> list[tuple[int | None, str, dict]]:
    """解析 SSE 为 (id, event, data);id 行是 A6 新增,旧客户端(无 id 解析)兼容。"""
    frames: list[tuple[int | None, str, dict]] = []
    event: str | None = None
    seq: int | None = None
    for line in resp.text.splitlines():
        if line.startswith("id: "):
            seq = int(line[4:].strip())
        elif line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: ") and event:
            frames.append((seq, event, json.loads(line[6:])))
            event, seq = None, None
    return frames


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.fixture()
async def boss_headers(client):
    """真实登录换 Bearer(与 analytics 路由套件同身份链路)。"""
    from engine_py.analytics import rbac

    await rbac.ensure_defaults("aurora")
    r = await client.post("/api/auth/login", json={"email": "test@example.com", "password": "agent-all-dev"})
    assert r.status_code == 200, r.text
    return {**TENANT, "Authorization": f"Bearer {r.json()['data']['token']}"}


@pytest.fixture()
def patch_ask(monkeypatch):
    """替换 graph.ask_all:返回预定 outcome 并计调用次数(重算即暴露)。"""
    calls = {"n": 0}

    def _patch(outcome):
        async def _fake(question, ctx, page_context=None):
            calls["n"] += 1
            return outcome

        monkeypatch.setattr("gateway_py.routers.analytics.graph.ask_all", _fake)

    return _patch, calls


class TestAskReplay:
    async def test_fresh_ask_returns_ask_id_and_frame_ids(self, client, boss_headers, patch_ask):
        _patch, _calls = patch_ask
        _patch({"type": "result", "metric": "gmv_trend", "rows": []})

        r = await client.post("/api/admin/analytics/ask", headers=boss_headers, json={"question": "上月GMV趋势"})
        assert r.status_code == 200
        ask_id = r.headers.get("x-ask-id")
        assert ask_id, "首连必须回 X-Ask-Id 供断线重连"

        frames = _sse_frames(r)
        assert [f[1] for f in frames] == ["start", "result"], "心跳/哨兵不出 SSE 线"
        assert frames[0][2]["askId"] == ask_id
        assert [f[0] for f in frames] == [1, 2], "每帧带自增 id"

    async def test_replay_resumes_without_recompute(self, client, boss_headers, patch_ask):
        _patch, calls = patch_ask
        _patch({"type": "result", "metric": "gmv_trend", "rows": []})

        first = await client.post("/api/admin/analytics/ask", headers=boss_headers, json={"question": "上月GMV趋势"})
        ask_id = first.headers["x-ask-id"]
        assert calls["n"] == 1

        # 客户端只收到 start(id=1)就断线:重连带 Last-Event-ID,只补 result,不重算
        resume = await client.post(
            "/api/admin/analytics/ask",
            headers={**boss_headers, "X-Ask-Id": ask_id, "Last-Event-ID": "1"},
            json={"question": "上月GMV趋势"},
        )
        assert resume.status_code == 200
        assert resume.headers["x-ask-id"] == ask_id
        assert calls["n"] == 1, "回放不得重算"
        assert [(f[0], f[1]) for f in _sse_frames(resume)] == [(2, "result")]

        # 不带 Last-Event-ID:全量回放
        full = await client.post(
            "/api/admin/analytics/ask",
            headers={**boss_headers, "X-Ask-Id": ask_id},
            json={"question": "上月GMV趋势"},
        )
        assert [(f[0], f[1]) for f in _sse_frames(full)] == [(1, "start"), (2, "result")]
        assert calls["n"] == 1

    async def test_replay_accepts_ask_id_in_body(self, client, boss_headers, patch_ask):
        """fetch 断线重连不便塞自定义头时的备用通道:body.askId 同义。"""
        _patch, calls = patch_ask
        _patch({"type": "unsupported", "message": "未命中"})

        first = await client.post("/api/admin/analytics/ask", headers=boss_headers, json={"question": "怪问题"})
        ask_id = first.headers["x-ask-id"]

        resume = await client.post(
            "/api/admin/analytics/ask",
            headers=boss_headers,
            json={"question": "怪问题", "askId": ask_id, "lastEventId": 1},
        )
        assert calls["n"] == 1
        assert [(f[0], f[1]) for f in _sse_frames(resume)] == [(2, "unsupported")]

    async def test_replay_unknown_ask_id_is_honest_error(self, client, boss_headers, patch_ask):
        _patch, calls = patch_ask
        _patch({"type": "result", "rows": []})

        r = await client.post(
            "/api/admin/analytics/ask",
            headers={**boss_headers, "X-Ask-Id": "ask_deadbeef", "Last-Event-ID": "1"},
            json={"question": "上月GMV趋势"},
        )
        assert r.status_code == 200
        frames = _sse_frames(r)
        assert len(frames) == 1 and frames[0][1] == "error"
        assert "重新提问" in frames[0][2]["message"]
        assert calls["n"] == 0, "过期流不得静默转重算(会出双份答案)"
