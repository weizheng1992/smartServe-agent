"""socket join/send 顾客属主闸 + store SSE userId 闸(2026-10-17 窃听族收口,
stream-1/stream-2/sec-1/sec-4)。

wire 协议不变(join_thread/send_message 事件与 ack 形状原样),收紧的是闸:
user 连接对有主线程必须 connect userId 精确等值,换房先退旧房。前端零 socket
客户端(web/merchant 无 join_thread 发射点),收紧免费;merchant-admin operator
面走 JWT+operate 权限闸,不入本闸。store SSE:有主线程必须声明匹配 userId,
否则 403(顾客弱身份模型下,默认线程 id 可由 userId 推得,本闸令「知线程 id
即听」失效)。
"""

from __future__ import annotations

import uuid as _uuid

import httpx
import socketio as socketio_lib
from engine_py.db import get_session
from sqlalchemy import text

from gateway_py.main import app

from .conftest import _TS, create_thread

_NS = "/ws/chat"


def _tid(tag: str) -> str:
    return f"gate_{tag}_{_TS}_{_uuid.uuid4().hex[:6]}"


async def _cleanup_threads(*tids: str) -> None:
    async with get_session() as session:
        for tid in tids:
            await session.execute(text("DELETE FROM messages WHERE thread_id = :t").bindparams(t=tid))
            await session.execute(text("DELETE FROM threads WHERE id = :t").bindparams(t=tid))
        await session.commit()


class TestUserThreadOwnerGate:
    """join_thread / send_message 的 user 侧属主闸(operator 不入此闸)。"""

    async def test_join_other_users_thread_denied(self, live_server):
        tid = _tid("own")
        await create_thread(tid, "u_gate_owner", "nike")
        intruder = socketio_lib.AsyncClient(reconnection=False)
        await intruder.connect(
            live_server, transports=["websocket"], namespaces=[_NS],
            auth={"tenantId": "nike", "userId": "u_gate_intruder", "role": "user"},
        )
        try:
            ack = await intruder.call(
                "join_thread", {"threadId": tid, "tenantId": "nike", "role": "user"},
                namespace=_NS, timeout=5,
            )
            assert ack["success"] is False
            assert "会话不属于当前用户" in ack["error"]
        finally:
            if intruder.connected:
                await intruder.disconnect()
            await _cleanup_threads(tid)

    async def test_join_missing_thread_denied(self, live_server):
        ghost = _tid("ghost")
        intruder = socketio_lib.AsyncClient(reconnection=False)
        await intruder.connect(
            live_server, transports=["websocket"], namespaces=[_NS],
            auth={"tenantId": "nike", "userId": "u_gate_user", "role": "user"},
        )
        try:
            ack = await intruder.call(
                "join_thread", {"threadId": ghost, "tenantId": "nike", "role": "user"},
                namespace=_NS, timeout=5,
            )
            assert ack["success"] is False
            assert "会话不存在" in ack["error"]
        finally:
            if intruder.connected:
                await intruder.disconnect()

    async def test_join_foreign_tenant_thread_denied(self, live_server):
        tid = _tid("cross")
        await create_thread(tid, "u_gate_owner", "nike")
        intruder = socketio_lib.AsyncClient(reconnection=False)
        await intruder.connect(
            live_server, transports=["websocket"], namespaces=[_NS],
            auth={"tenantId": "adidas", "userId": "u_gate_owner", "role": "user"},
        )
        try:
            # userId 即便对上,他租线程仍拒(租户一致是属主闸的前置半边)
            ack = await intruder.call(
                "join_thread", {"threadId": tid, "tenantId": "adidas", "role": "user"},
                namespace=_NS, timeout=5,
            )
            assert ack["success"] is False
            assert "会话不属于该商户" in ack["error"]
        finally:
            if intruder.connected:
                await intruder.disconnect()
            await _cleanup_threads(tid)

    async def test_rejoin_leaves_previous_room(self, live_server):
        """换房退旧房(stream-2):join A → join B 后,发往 A 房的 new_message
        不得再达该连接;发往 B 房的必须到达。"""
        ta, tb = _tid("room_a"), _tid("room_b")
        await create_thread(ta, "u_gate_owner", "nike")
        await create_thread(tb, "u_gate_owner", "nike")
        owner = socketio_lib.AsyncClient(reconnection=False)
        received: list[dict] = []
        owner.on("new_message", lambda p=None: received.append(p or {}), namespace=_NS)
        await owner.connect(
            live_server, transports=["websocket"], namespaces=[_NS],
            auth={"tenantId": "nike", "userId": "u_gate_owner", "role": "user"},
        )
        try:
            for tid in (ta, tb):
                ack = await owner.call(
                    "join_thread", {"threadId": tid, "tenantId": "nike", "role": "user"},
                    namespace=_NS, timeout=5,
                )
                assert ack["success"] is True

            # 发往旧房 A:发送者本人是属主,发言放行;但该连接已退房,不得收到
            old = await owner.call(
                "send_message", {"threadId": ta, "tenantId": "nike", "role": "user", "content": "旧房帧"},
                namespace=_NS, timeout=5,
            )
            assert old["success"] is True
            # 发往新房 B:必须收到
            new = await owner.call(
                "send_message", {"threadId": tb, "tenantId": "nike", "role": "user", "content": "新房帧"},
                namespace=_NS, timeout=5,
            )
            assert new["success"] is True

            import asyncio

            await asyncio.sleep(0.5)
            contents = [r.get("content") for r in received]
            assert "新房帧" in contents, f"新房帧必须到达: {contents}"
            assert "旧房帧" not in contents, f"旧房帧不得再达(退旧房): {contents}"
        finally:
            if owner.connected:
                await owner.disconnect()
            await _cleanup_threads(ta, tb)


class TestStoreStreamUserGate:
    """store SSE 顾客属主闸:有主线程必须声明匹配 userId。"""

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def _mk(self, tag: str) -> str:
        tid = _tid(tag)
        await create_thread(tid, "u_gate_stream", "adidas")
        return tid

    async def test_owned_thread_without_user_id_403(self, live_server):
        tid = await self._mk("nouid")
        try:
            async with self._client() as c:
                res = await c.get(
                    "/api/store/chat/stream", params={"threadId": tid, "businessId": "adidas"}
                )
            assert res.status_code == 403
            assert "会话不属于当前用户" in res.json()["error"]
        finally:
            await _cleanup_threads(tid)

    async def test_owned_thread_wrong_user_403(self, live_server):
        tid = await self._mk("wrong")
        try:
            async with self._client() as c:
                res = await c.get(
                    "/api/store/chat/stream",
                    params={"threadId": tid, "businessId": "adidas", "userId": "u_gate_other"},
                )
            assert res.status_code == 403
            assert "会话不属于当前用户" in res.json()["error"]
        finally:
            await _cleanup_threads(tid)

    async def test_owned_thread_matching_user_connects(self, live_server):
        """属主订阅放行:首帧 event: connected(SSE 必须 live_server 真网络栈)。"""
        tid = await self._mk("ok")
        try:
            timeout = httpx.Timeout(10.0, read=15.0)
            async with httpx.AsyncClient(base_url=live_server, timeout=timeout) as hc, hc.stream(
                "GET",
                f"{live_server}/api/store/chat/stream",
                params={"threadId": tid, "businessId": "adidas", "userId": "u_gate_stream"},
            ) as res:
                assert res.status_code == 200
                assert "text/event-stream" in res.headers["content-type"]
                buf = ""
                async for chunk in res.aiter_text():
                    buf += chunk
                    if "event: connected" in buf:
                        break
                assert "event: connected" in buf, f"未收到 connected 帧: {buf[-300:]!r}"
        finally:
            await _cleanup_threads(tid)
