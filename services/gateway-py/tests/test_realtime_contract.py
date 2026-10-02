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

    async def test_client_abort_midstream_then_reconnect(self, live_server):
        """客户端中途断开:SSE 泵随连接终止且服务端不受污染;作业事件主干
        照常累积,重连按 Last-Event-ID 只补缺失帧(夜审 2026-09-29 补:
        SSE 中途断流此前零测试 —— 观察面断开不等于事件面蒸发)。"""
        import httpx
        from engine_py.event_bus import emit

        job_id = f"job_rt_abort_{_TS}"
        timeout = httpx.Timeout(10.0, read=30.0)
        # 连接前灌入首帧:断流测试的读窗即刻可达,不依赖灌入竞态
        await emit(job_id, "thought", {"jobId": job_id, "step": "断流前帧"})
        await asyncio.sleep(0.1)

        async with httpx.AsyncClient(base_url=live_server, timeout=timeout) as client:

            async def read_first_then_abort():
                async with client.stream("GET", f"/api/chat/{job_id}/stream") as res:
                    assert res.status_code == 200
                    buf = ""
                    async for chunk in res.aiter_text():
                        buf += chunk
                        if "event: thought" in buf:
                            return  # 帧体读到即退出 stream 上下文 = 客户端中途断开

            # 断开必须干脆(服务端若挂死泵,uvicorn 取消会话时此处会超时暴露)
            await asyncio.wait_for(read_first_then_abort(), 10)

        # 断开后事件照常入流(作业面独立于观察面),重连只补缺失帧
        await emit(job_id, "thought", {"jobId": job_id, "step": "断流后新帧"})
        raw = ""
        async with httpx.AsyncClient(base_url=live_server, timeout=timeout) as client, client.stream(
            "GET", f"/api/chat/{job_id}/stream", headers={"last-event-id": "1"}
        ) as res:
            assert res.status_code == 200
            async for chunk in res.aiter_text():
                raw += chunk
                if "断流后新帧" in raw:
                    break

        assert re.search(r"^id: 2\nevent: thought.*断流后新帧", raw, re.DOTALL), "重连必须以 id 2 补发断流后新帧"
        assert "id: 1\n" not in raw, "已收帧(seq=1)严禁重放"


class TestSocketIoChat:
    async def test_five_event_full_protocol(self, live_server, rt_thread, nike_operator):
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
        # 02 安全先行:operator 连接必须持员工 JWT;join/takeover 里的自报
        # operatorId/Name 为遗留字段,服务端一律以 JWT 派生身份覆盖
        await operator.connect(
            base_url,
            transports=["websocket"],
            namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_rt_operator", "role": "operator", "token": nike_operator["token"]},
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
                    "operatorName": "自报假名(应被服务端身份覆盖)",
                },
                namespace=ns,
                timeout=5,
            )
            assert join_ack["threadId"] == rt_thread
            assert join_ack["tenantId"] == "nike"
            await wait_for(lambda: any(r["event"] == "joined_room" for r in received))
            await wait_for(
                lambda: any(
                    r["event"] == "peer_joined" and r["payload"].get("operatorName") == nike_operator["name"]
                    for r in received
                )
            )

            # takeover → conversation_state_changed(human_takeover,含服务端派生 operatorName)
            await operator.call(
                "takeover_conversation",
                {
                    "threadId": rt_thread,
                    "tenantId": "nike",
                    "operatorId": f"op_{_TS}",
                    "operatorName": "自报假名(应被服务端身份覆盖)",
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
            assert takeover_event["payload"]["operatorId"] == nike_operator["email"]
            assert takeover_event["payload"]["operatorName"] == nike_operator["name"]

            # send_message → new_message + ack {success, messageId}
            send_ack = await operator.call(
                "send_message",
                {
                    "threadId": rt_thread,
                    "tenantId": "nike",
                    "role": "operator",
                    "content": "契约测试:人工坐席消息",
                    "operatorInfo": {"operatorId": "spoofed", "operatorName": "自报假名"},
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
            assert msg_event["payload"]["operatorInfo"]["operatorId"] == nike_operator["email"]

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
                {"threadId": rt_thread, "tenantId": "nike"},
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

    async def test_operator_connect_without_token_rejected(self, live_server):
        """02 安全先行:operator 连接缺员工 JWT → 服务端拒绝连接。"""
        import socketio as socketio_lib
        from socketio.exceptions import ConnectionError as SocketIOConnectionError

        ns = "/ws/chat"
        rogue = socketio_lib.AsyncClient(reconnection=False)
        with pytest.raises(SocketIOConnectionError):
            await rogue.connect(
                live_server, transports=["websocket"], namespaces=[ns],
                auth={"tenantId": "nike", "userId": "u_rogue_op", "role": "operator"},
            )
        assert not rogue.connected

    async def test_operator_connect_tenant_mismatch_rejected(self, live_server, nike_operator):
        """02 安全先行:员工 JWT 有效但其租户与 connect tenantId 不一致 → 拒绝。"""
        import socketio as socketio_lib
        from socketio.exceptions import ConnectionError as SocketIOConnectionError

        ns = "/ws/chat"
        rogue = socketio_lib.AsyncClient(reconnection=False)
        with pytest.raises(SocketIOConnectionError):
            await rogue.connect(
                live_server, transports=["websocket"], namespaces=[ns],
                auth={"tenantId": "adidas", "userId": "u_rogue_op", "role": "operator", "token": nike_operator["token"]},
            )
        assert not rogue.connected

    async def test_takeover_from_unauthenticated_connection_denied(self, live_server, rt_thread):
        """02 安全先行:user 连接(无员工身份)调 takeover → 事件级拒绝,状态不变。"""
        import socketio as socketio_lib
        from engine_py.db import get_session
        from sqlalchemy import text

        ns = "/ws/chat"
        intruder = socketio_lib.AsyncClient(reconnection=False)
        await intruder.connect(
            live_server, transports=["websocket"], namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_intruder", "role": "user"},
        )
        try:
            ack = await intruder.call(
                "takeover_conversation",
                {"threadId": rt_thread, "tenantId": "nike", "operatorId": "u_intruder", "operatorName": "冒充坐席"},
                namespace=ns, timeout=5,
            )
            assert ack["success"] is False
            assert "未认证" in ack["error"]
            async with get_session() as session:
                row = (
                    await session.execute(
                        text("SELECT status FROM threads WHERE id = :tid"), {"tid": rt_thread}
                    )
                ).first()
            assert row[0] != "human_takeover"
        finally:
            if intruder.connected:
                await intruder.disconnect()


class TestSocketIoEdgeStates:
    """断连/越权边缘态专项(2026-09-26 夜审 ④ 收口)。

    五事件全协议测试只走 happy path;此处钉死三处易回归边缘:
    1. release 传 None 显式清空 assigned_operator_id(与 ``__unset__`` 哨兵
       「不动列」语义相反 —— 保留旧坐席会让 active 会话看起来仍被接管);
    2. 未 join 的连接断开零广播(on_disconnect 的 threadId 守卫);
    3. 非法租户名 connect 被服务端拒绝(_TENANT_RE 白名单)。"""

    async def test_release_clears_assigned_operator(self, live_server, rt_thread, nike_operator):
        import socketio as socketio_lib
        from engine_py.db import get_session
        from sqlalchemy import text

        ns = "/ws/chat"
        operator = socketio_lib.AsyncClient(reconnection=False)
        await operator.connect(
            live_server, transports=["websocket"], namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_edge_op", "role": "operator", "token": nike_operator["token"]},
        )
        try:
            await operator.call(
                "join_thread", {"threadId": rt_thread, "tenantId": "nike", "role": "operator"},
                namespace=ns, timeout=5,
            )
            # 坐席身份服务端派生(JWT email),客户端自报不再落库
            op_id = nike_operator["email"]
            await operator.call(
                "takeover_conversation", {"threadId": rt_thread, "tenantId": "nike"},
                namespace=ns, timeout=5,
            )

            async def _row():
                async with get_session() as session:
                    return (
                        await session.execute(
                            text("SELECT status, assigned_operator_id FROM threads WHERE id = :tid"),
                            {"tid": rt_thread},
                        )
                    ).first()

            row = await _row()
            assert row[0] == "human_takeover"
            assert row[1] == op_id, "takeover 必须落坐席"

            await operator.call(
                "release_takeover", {"threadId": rt_thread, "tenantId": "nike"}, namespace=ns, timeout=5
            )
            row = await _row()
            assert row[0] == "active"
            assert row[1] is None, "release 必须显式清空坐席(None ≠ __unset__ 哨兵)"
        finally:
            if operator.connected:
                await operator.disconnect()

    async def test_disconnect_without_join_is_silent(self, live_server, rt_thread, nike_operator):
        import asyncio

        import socketio as socketio_lib

        ns = "/ws/chat"
        listener = socketio_lib.AsyncClient(reconnection=False)
        phantom = socketio_lib.AsyncClient(reconnection=False)
        peer_events: list[dict] = []
        listener.on(
            "peer_disconnected", lambda p=None: peer_events.append(p or {}), namespace=ns
        )
        await listener.connect(
            live_server, transports=["websocket"], namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_edge_listener", "role": "operator", "token": nike_operator["token"]},
        )
        await listener.call(
            "join_thread", {"threadId": rt_thread, "tenantId": "nike", "role": "operator"},
            namespace=ns, timeout=5,
        )
        # 幽灵客户端:连上但永不 join(threadId 为空)→ 断开不得广播 peer_disconnected
        await phantom.connect(
            live_server, transports=["websocket"], namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_edge_phantom", "role": "user"},
        )
        try:
            await phantom.disconnect()
            await asyncio.sleep(0.5)  # 负断言:给误广播留出暴露窗口
            assert peer_events == [], "未 join 的断开不得广播 peer_disconnected"
        finally:
            if listener.connected:
                await listener.disconnect()

    async def test_invalid_tenant_connect_rejected(self, live_server):
        import pytest
        import socketio as socketio_lib
        from socketio.exceptions import ConnectionError as SocketIOConnectionError

        ns = "/ws/chat"
        rogue = socketio_lib.AsyncClient(reconnection=False)
        with pytest.raises(SocketIOConnectionError):
            await rogue.connect(
                live_server, transports=["websocket"], namespaces=[ns],
                auth={"tenantId": "bad tenant; DROP", "userId": "u_edge_rogue", "role": "user"},
            )
        assert not rogue.connected

    async def test_operator_message_reaches_store_sse(self, live_server, rt_thread, nike_operator):
        """坐席消息必须桥进顾客 store SSE 频道(thread:{id}:message)。

        回归钉(2026-09-29 实弹):坐席 send_message 此前只走 socket 房间广播 +
        ws:events 频道(无消费者),而商户商城顾客端(apps/merchant)唯一实时
        耳朵是 GET /api/store/chat/stream 订阅的 thread:{id}:message —— 坐席
        「已接管」连发数条,顾客一条收不到只会回「?」。真栈验证:socket 落库
        后,顾客 SSE 流须在窗口内收到同 id 同内容的 operator 帧。
        """
        import httpx
        import socketio as socketio_lib

        ns = "/ws/chat"
        content = f"回归钉:坐席消息须达顾客 SSE {_TS}"
        operator = socketio_lib.AsyncClient(reconnection=False)
        await operator.connect(
            live_server,
            transports=["websocket"],
            namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_rt_operator", "role": "operator", "token": nike_operator["token"]},
        )
        try:
            # 认领闸(2026-09-29):坐席发言前须处接管态 —— 先认领再开流
            takeover_ack = await operator.call(
                "takeover_conversation", {"threadId": rt_thread, "tenantId": "nike"}, namespace=ns, timeout=5
            )
            assert takeover_ack["success"] is True
            raw = ""
            sent = False
            timeout = httpx.Timeout(10.0, read=20.0)
            async with httpx.AsyncClient(base_url=live_server, timeout=timeout) as client, client.stream(
                # businessId 自报(2026-10-02 属主闸,29beb83):流订阅必须携带
                # 商户身份,缺省回落 aurora 与本线程属主 nike 不符即 403
                "GET", f"/api/store/chat/stream?threadId={rt_thread}&businessId=nike"
            ) as res:
                assert res.status_code == 200
                # 单循环双闸(httpx 流只能消费一次):先等到 connected 帧(订阅
                # 就绪)再让坐席发言 —— 镜像顾客端真实时序(EventSource 常驻
                # 先挂);Redis pub/sub 无重放,订阅前发布的帧物理不可见。
                # 桥通则坐席帧即时到达;read=20s 兜底 heartbeat 节拍(15s)前必判。
                async for chunk in res.aiter_text():
                    raw += chunk
                    if not sent and "event: connected" in raw:
                        sent = True
                        send_ack = await operator.call(
                            "send_message",
                            {"threadId": rt_thread, "tenantId": "nike", "role": "operator", "content": content},
                            namespace=ns,
                            timeout=5,
                        )
                        assert send_ack["success"] is True
                    if sent and content in raw:
                        break

            assert sent, "SSE 流未就绪(connected 帧未到)"
            assert content in raw, f"坐席消息未达顾客 SSE 频道: {raw[-400:]}"
            assert '"role": "operator"' in raw
        finally:
            # 还原模块级共享线程状态(后续测试不背接管态);顺带钉释放桥
            await operator.call(
                "release_takeover", {"threadId": rt_thread, "tenantId": "nike"}, namespace=ns, timeout=5
            )
            if operator.connected:
                await operator.disconnect()

    async def test_send_to_active_thread_rejected(self, live_server, rt_thread, nike_operator):
        """认领闸(2026-09-29):未接管(active)会话坐席禁言 —— 此前坐席可对
        AI 托管中的会话直插 operator 发言,顾客端出现「AI 与真人各说各话」;
        实弹事故里 14:45 转人工后 AI 罐头与坐席发言混流的第二根源。"""
        import socketio as socketio_lib
        from engine_py.approvals import takeover

        ns = "/ws/chat"
        operator = socketio_lib.AsyncClient(reconnection=False)
        await operator.connect(
            live_server, transports=["websocket"], namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_gate_op", "role": "operator", "token": nike_operator["token"]},
        )
        try:
            ack = await operator.call(
                "send_message",
                {"threadId": rt_thread, "tenantId": "nike", "role": "operator", "content": "未认领禁言"},
                namespace=ns, timeout=5,
            )
            assert ack["success"] is False
            assert "未被接管" in ack["error"]
            assert (await takeover.thread_state(rt_thread))["status"] == "active"
        finally:
            if operator.connected:
                await operator.disconnect()

    async def test_send_to_queued_thread_auto_claims(self, live_server, nike_operator):
        """认领闸的 UX 面(2026-09-29):呼叫中(接管态+坐席空)首发即原子认领
        —— 坐席台 sendMessage 不先点接管(live-desk P2 认领池语义「败者得
        False」在发言路同样成立),落库后真源必须已带认领坐席。"""
        import socketio as socketio_lib
        from engine_py.approvals import takeover

        tid = f"rt_auto_claim_{_TS}"
        await create_thread(tid, "u_auto_claim", "nike")
        await takeover.mark_takeover_requested(tid)  # 顾客呼叫:排队态
        assert (await takeover.thread_state(tid))["assignedOperatorId"] is None

        ns = "/ws/chat"
        operator = socketio_lib.AsyncClient(reconnection=False)
        await operator.connect(
            live_server, transports=["websocket"], namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_auto_claim_op", "role": "operator", "token": nike_operator["token"]},
        )
        try:
            ack = await operator.call(
                "send_message",
                {"threadId": tid, "tenantId": "nike", "role": "operator", "content": "发言即认领"},
                namespace=ns, timeout=5,
            )
            assert ack["success"] is True
            state = await takeover.thread_state(tid)
            assert state["status"] == "human_takeover"
            assert state["assignedOperatorId"] == nike_operator["email"], "排队首发必须自动落认领"
        finally:
            if operator.connected:
                await operator.disconnect()

    async def test_send_to_other_operator_claim_rejected(self, live_server, nike_operator):
        """认领闸的守卫面(2026-09-29):会话已被坐席 A 认领,坐席 B 发言被拒
        —— assign_operator 原子守卫的发言路对齐(两坐席同抢只成一人)。"""
        import socketio as socketio_lib
        from engine_py.analytics import rbac
        from engine_py.approvals import takeover
        from engine_py.db import StaffMember, get_session

        from gateway_py.routers.auth import issue_token

        tid = f"rt_dual_op_{_TS}"
        await create_thread(tid, "u_dual_op", "nike")

        # 坐席 B:直插员工行直签 JWT(与 nike_operator fixture 同基建)
        await rbac.ensure_menu_seed("nike")
        email_b = f"op-nike-b-{_TS}@nike.test"
        async with get_session() as session:
            session.add(StaffMember(
                id=f"staff_nike_b_{_TS}", business_id="nike", email=email_b,
                display_name="耐克坐席B", role="admin", status="enabled", password_hash=None,
            ))
            await session.commit()

        ns = "/ws/chat"
        op_a = socketio_lib.AsyncClient(reconnection=False)
        op_b = socketio_lib.AsyncClient(reconnection=False)
        await op_a.connect(
            live_server, transports=["websocket"], namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_op_a", "role": "operator", "token": nike_operator["token"]},
        )
        await op_b.connect(
            live_server, transports=["websocket"], namespaces=[ns],
            auth={"tenantId": "nike", "userId": "u_op_b", "role": "operator", "token": issue_token(f"staff_nike_b_{_TS}", email_b)},
        )
        try:
            claim_a = await op_a.call(
                "takeover_conversation", {"threadId": tid, "tenantId": "nike"}, namespace=ns, timeout=5
            )
            assert claim_a["success"] is True
            ack_b = await op_b.call(
                "send_message",
                {"threadId": tid, "tenantId": "nike", "role": "operator", "content": "他人认领禁言"},
                namespace=ns, timeout=5,
            )
            assert ack_b["success"] is False
            assert "认领" in ack_b["error"]
            # 认领路同一守卫:B 显式接管同样被拒,真源认领人不变
            claim_b = await op_b.call(
                "takeover_conversation", {"threadId": tid, "tenantId": "nike"}, namespace=ns, timeout=5
            )
            assert claim_b["success"] is False
            assert (await takeover.thread_state(tid))["assignedOperatorId"] == nike_operator["email"]
        finally:
            await op_a.call(
                "release_takeover", {"threadId": tid, "tenantId": "nike"}, namespace=ns, timeout=5
            )
            for c in (op_a, op_b):
                if c.connected:
                    await c.disconnect()
