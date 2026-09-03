"""📜 实时契约测试(SSE + socket.io)— 1:1 移植 apps/server/test/contract/realtime.contract.test.ts。

1. SSE:GET /api/chat/:jobId/stream
   - 响应头:text/event-stream / no-cache
   - 帧格式:`id: <seq>` + `event: <thought|cards|result>` + `data: {json}`
   - Last-Event-ID 重连重放(只补发 seq > lastEventId 的事件)
2. socket.io namespace /ws/chat:
   join_thread → joined_room(ack) + peer_joined(房间广播)
   takeover/release → conversation_state_changed(含 operatorName / systemMessage)
   send_message → new_message + ack {success, messageId}
   typing → user_typing(房间广播,排除发送者 — 用双客户端验证)
   断开 → peer_disconnected

事件驱动:TS 侧经 agentEventEmitter,Python 侧事件源就是 Redis Streams 本身,
测试直接调用 engine_py.event_bus.emit 灌入事件。
"""

from __future__ import annotations

import asyncio
import re

import pytest
import pytest_asyncio

from .conftest import _TS, RT_THREAD, create_thread, wait_for

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def rt_thread(seeded):
    """socket.io takeover/release 会更新会话状态,需要 thread fixture。"""
    await create_thread(RT_THREAD, "u_rt_contract", "nike")
    return RT_THREAD


class TestSseStream:
    async def test_headers_frame_format_and_id_sequence(self, live_server):
        """SSE 契约必须走真网络栈(live_server)。

        httpx ASGITransport 会把整个 ASGI app 跑到完成才进入 stream 上下文,
        "连接建立后灌入事件"在 in-process 传输下结构性死锁(app 等事件、
        测试等 app);真 TCP 下响应头立即返回、服务端与测试体并发运行,
        才能还原 TS 基线(supertest over real HTTP)的时序。
        """
        import httpx
        from engine_py.event_bus import emit

        job_id = f"job_rt_{_TS}"
        raw = ""
        timeout = httpx.Timeout(10.0, read=30.0)
        async with (
            httpx.AsyncClient(base_url=live_server, timeout=timeout) as client,
            client.stream("GET", f"/api/chat/{job_id}/stream") as res,
        ):
            assert res.status_code == 200
            assert "text/event-stream" in res.headers["content-type"]
            assert "no-cache" in res.headers["cache-control"]

            # 连接建立后灌入 2 个 thought + 1 个 result
            await asyncio.sleep(0.1)
            await emit(job_id, "thought", {"jobId": job_id, "step": "RT 契约步骤 1"})
            await emit(job_id, "thought", {"jobId": job_id, "step": "RT 契约步骤 2"})
            await emit(job_id, "result", {"jobId": job_id, "output": "RT 契约最终回答", "cards": []})

            async for chunk in res.aiter_text():
                raw += chunk
                if "event: result" in raw:
                    break

        blocks = [b for b in raw.split("\n\n") if b.strip()]
        event_blocks = [b for b in blocks if b.startswith("id:")]
        assert len(event_blocks) >= 3
        assert re.match(r"^id: 1\nevent: thought\ndata: \{.*\}$", event_blocks[0])
        assert re.match(r"^id: 2\nevent: thought\ndata: \{.*\}$", event_blocks[1])
        assert re.match(r"^id: 3\nevent: (cards|result)\ndata: \{.*\}$", event_blocks[2])

    async def test_last_event_id_replay_only_missing(self, live_server):
        # 与 test 1 同理走真网络栈:重放后无 result,流会持续心跳等待,
        # in-process 传输下(app 必须跑完)永不结束。
        import httpx
        from engine_py.event_bus import emit

        job_id = f"job_rt_replay_{_TS}"
        # Redis Streams 即事件源:无需先建立连接,发布后历史天然持久
        await emit(job_id, "thought", {"jobId": job_id, "step": "重放事件 1"})
        await emit(job_id, "thought", {"jobId": job_id, "step": "重放事件 2"})
        await emit(job_id, "thought", {"jobId": job_id, "step": "重放事件 3"})
        await asyncio.sleep(0.1)

        raw = ""
        timeout = httpx.Timeout(10.0, read=30.0)
        async with (
            httpx.AsyncClient(base_url=live_server, timeout=timeout) as client,
            client.stream(
                "GET", f"/api/chat/{job_id}/stream", headers={"last-event-id": "1"}
            ) as res2,
        ):
            assert res2.status_code == 200
            async for chunk in res2.aiter_text():
                raw += chunk
                if "id: 3" in raw:
                    break

        # 只应补发 id 2、3;不得重复 id 1
        assert "id: 2" in raw
        assert "id: 3" in raw
        assert "id: 1\n" not in raw


class TestSocketIoChat:
    async def test_five_event_full_protocol(self, live_server, rt_thread):
        import socketio as socketio_lib

        ns = "/ws/chat"
        base_url = live_server
        operator = socketio_lib.AsyncClient(reconnection=False)
        user = socketio_lib.AsyncClient(reconnection=False)

        received: list[dict] = []

        def _collect(event):
            def handler(payload=None):
                received.append({"event": event, "payload": payload})

            return handler

        for evt in (
            "joined_room",
            "peer_joined",
            "conversation_state_changed",
            "new_message",
            "user_typing",
            "peer_disconnected",
        ):
            operator.on(evt, _collect(evt), namespace=ns)
            user.on(evt, _collect(evt), namespace=ns)

        await user.connect(
            base_url,
            transports=["websocket"],
            namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_rt_user", "role": "user"},
        )
        await operator.connect(
            base_url,
            transports=["websocket"],
            namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_rt_operator", "role": "operator"},
        )

        try:
            # 双方各自 join → 对端 peer_joined + 自己 joined_room ack
            user_join_ack = await user.call(
                "join_thread",
                {"threadId": rt_thread, "tenantId": "nike", "role": "user"},
                namespace=ns,
                timeout=5,
            )
            assert user_join_ack["threadId"] == rt_thread
            assert user_join_ack["tenantId"] == "nike"

            join_ack = await operator.call(
                "join_thread",
                {
                    "threadId": rt_thread,
                    "tenantId": "nike",
                    "role": "operator",
                    "operatorId": f"op_{_TS}",
                    "operatorName": "契约测试坐席",
                },
                namespace=ns,
                timeout=5,
            )
            assert join_ack["threadId"] == rt_thread
            assert join_ack["tenantId"] == "nike"
            await wait_for(lambda: any(r["event"] == "joined_room" for r in received))
            await wait_for(
                lambda: any(
                    r["event"] == "peer_joined" and r["payload"].get("operatorName") == "契约测试坐席"
                    for r in received
                )
            )

            # takeover → conversation_state_changed(human_takeover,含 operatorName)
            await operator.call(
                "takeover_conversation",
                {
                    "threadId": rt_thread,
                    "tenantId": "nike",
                    "operatorId": f"op_{_TS}",
                    "operatorName": "契约测试坐席",
                },
                namespace=ns,
                timeout=5,
            )
            await wait_for(
                lambda: any(
                    r["event"] == "conversation_state_changed"
                    and r["payload"].get("status") == "human_takeover"
                    for r in received
                )
            )
            takeover_event = next(
                r
                for r in received
                if r["event"] == "conversation_state_changed" and r["payload"].get("status") == "human_takeover"
            )
            assert takeover_event["payload"]["operatorName"] == "契约测试坐席"

            # send_message → new_message + ack {success, messageId}
            send_ack = await operator.call(
                "send_message",
                {
                    "threadId": rt_thread,
                    "tenantId": "nike",
                    "role": "operator",
                    "content": "契约测试:人工坐席消息",
                    "operatorInfo": {"operatorId": f"op_{_TS}", "operatorName": "契约测试坐席"},
                },
                namespace=ns,
                timeout=5,
            )
            assert send_ack["success"] is True
            assert "messageId" in send_ack
            await wait_for(lambda: any(r["event"] == "new_message" for r in received))
            msg_event = next(r for r in received if r["event"] == "new_message")
            assert msg_event["payload"]["content"] == "契约测试:人工坐席消息"
            assert msg_event["payload"]["id"] == send_ack["messageId"]

            # typing → user_typing 广播到房间但排除发送者(双客户端语义)
            operator_events_before = sum(1 for r in received if r["event"] == "user_typing")
            await operator.call(
                "typing", {"threadId": rt_thread, "tenantId": "nike", "isTyping": True}, namespace=ns, timeout=5
            )
            await wait_for(
                lambda: sum(1 for r in received if r["event"] == "user_typing") > operator_events_before
            )
            typing_events = [r for r in received if r["event"] == "user_typing"]
            # 排除发送者:operator 不应收到自己触发的 typing,只有 user 收到
            assert len(typing_events) == operator_events_before + 1

            # release → 第二次 conversation_state_changed
            await operator.call(
                "release_takeover",
                {"threadId": rt_thread, "tenantId": "nike", "operatorId": f"op_{_TS}"},
                namespace=ns,
                timeout=5,
            )
            await wait_for(
                lambda: sum(1 for r in received if r["event"] == "conversation_state_changed") >= 2
            )
            release_event = [
                r for r in received if r["event"] == "conversation_state_changed"
            ][-1]
            assert release_event["payload"]["status"] == "active"

            # operator 断开 → user 收到 peer_disconnected
            await operator.disconnect()
            await wait_for(lambda: any(r["event"] == "peer_disconnected" for r in received))
        finally:
            if operator.connected:
                await operator.disconnect()
            if user.connected:
                await user.disconnect()
