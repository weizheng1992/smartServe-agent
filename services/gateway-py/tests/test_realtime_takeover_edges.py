"""socket.io 接管态机边缘专项(realtime.py)— 补主契约套件(test_realtime_contract.py)未覆盖的断连/清空语义。

钉死五件事:
1. ``__unset__`` 哨兵语义(conversation_repo.update_conversation_status):
   缺省(不带第 4 参)保留 assigned_operator_id 不动;显式 None 才清空 ——
   release_takeover 正是借显式 None 清坐席,而 SPI close 等纯状态变更
   (sentinel 缺省)不得顺手抹掉坐席归属;
2. takeover/release 的 conversation_state_changed 载荷契约:takeover 携
   operatorId/operatorName + role=system 的 systemMessage;release 回 active
   带 systemMessage 但不含坐席字段;
3. 坐席中途退出:对端收 peer_disconnected(role=operator),但会话状态
   **不自动回退**(仍 human_takeover,断开≠release —— 恢复 AI 托管必须是显式动作);
4. 非法租户 auth 拒绝连接(tenant 正则 ^[a-zA-Z0-9_-]{1,64}$);
5. send_message 非法 role 落库归一为 operator(白名单外的都不得冒充
   user/assistant/system 写入他人时间线)。

wire 用例沿用主套件的 live_server 真网络栈(in-process 传输下 socket.io
事件时序结构性失真,见主套件 SSE 用例注释)。
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from .conftest import _TS, create_thread, wait_for

pytestmark = pytest.mark.asyncio(loop_scope="session")

EDGE_THREAD = f"rt_edge_thread_{_TS}"
EDGE_THREAD_2 = f"rt_edge_thread2_{_TS}"
_NS = "/ws/chat"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def edge_threads(seeded):
    await create_thread(EDGE_THREAD, "u_edge_user", "nike")
    await create_thread(EDGE_THREAD_2, "u_edge_user", "nike")
    return (EDGE_THREAD, EDGE_THREAD_2)


async def _connect_pair(base_url: str, thread_id: str):
    """双客户端接入同一房间:operator + user,共享事件收集列表。"""
    import socketio as socketio_lib

    operator = socketio_lib.AsyncClient(reconnection=False)
    user = socketio_lib.AsyncClient(reconnection=False)
    received: list[dict] = []

    def _collect(event):
        def handler(payload=None):
            received.append({"event": event, "payload": payload})

        return handler

    for evt in ("conversation_state_changed", "peer_disconnected", "new_message"):
        operator.on(evt, _collect(evt), namespace=_NS)
        user.on(evt, _collect(evt), namespace=_NS)

    await user.connect(
        base_url,
        transports=["websocket"],
        namespaces=[_NS],
        auth={"tenantId": "nike", "userId": "u_edge_user", "role": "user"},
    )
    await operator.connect(
        base_url,
        transports=["websocket"],
        namespaces=[_NS],
        auth={"tenantId": "nike", "userId": "u_edge_operator", "role": "operator"},
    )
    await user.call(
        "join_thread", {"threadId": thread_id, "tenantId": "nike", "role": "user"}, namespace=_NS, timeout=5
    )
    await operator.call(
        "join_thread",
        {
            "threadId": thread_id,
            "tenantId": "nike",
            "role": "operator",
            "operatorId": f"op_edge_{_TS}",
            "operatorName": "边缘测试坐席",
        },
        namespace=_NS,
        timeout=5,
    )
    return operator, user, received


# ---------- wire 语义(live_server) ----------


class TestTakeoverReleaseEdges:
    async def test_takeover与release的state_changed载荷契约(self, live_server, edge_threads):
        from gateway_py import conversation_repo

        thread_id, _ = edge_threads
        operator, user, received = await _connect_pair(live_server, thread_id)
        try:
            await operator.call(
                "takeover_conversation",
                {
                    "threadId": thread_id,
                    "tenantId": "nike",
                    "operatorId": f"op_edge_{_TS}",
                    "operatorName": "边缘测试坐席",
                },
                namespace=_NS,
                timeout=5,
            )
            await wait_for(
                lambda: any(
                    r["event"] == "conversation_state_changed"
                    and r["payload"].get("status") == "human_takeover"
                    for r in received
                )
            )
            takeover = next(
                r
                for r in received
                if r["event"] == "conversation_state_changed" and r["payload"].get("status") == "human_takeover"
            )
            assert takeover["payload"]["operatorId"] == f"op_edge_{_TS}"
            assert takeover["payload"]["operatorName"] == "边缘测试坐席"
            assert takeover["payload"]["systemMessage"]["role"] == "system"
            assert "已接入" in takeover["payload"]["systemMessage"]["content"]

            await operator.call(
                "release_takeover",
                {"threadId": thread_id, "tenantId": "nike", "operatorId": f"op_edge_{_TS}"},
                namespace=_NS,
                timeout=5,
            )
            await wait_for(
                lambda: sum(
                    1
                    for r in received
                    if r["event"] == "conversation_state_changed" and r["payload"].get("status") == "active"
                )
                >= 1
            )
            release = next(
                r
                for r in received
                if r["event"] == "conversation_state_changed" and r["payload"].get("status") == "active"
            )
            assert "operatorId" not in release["payload"]
            assert "operatorName" not in release["payload"]
            assert release["payload"]["systemMessage"]["role"] == "system"
            assert "重新切换" in release["payload"]["systemMessage"]["content"]

            # release = 显式 None 清坐席:落库后 status active 且 assigned_operator_id 空
            timeline = await conversation_repo.get_conversation_timeline(thread_id, "nike")
            assert timeline["thread"]["status"] == "active"
            assert timeline["thread"]["assignedOperatorId"] is None
        finally:
            if operator.connected:
                await operator.disconnect()
            if user.connected:
                await user.disconnect()

    async def test_坐席中途退出_对端peer_disconnected_状态不自动回退(self, live_server, edge_threads):
        from gateway_py import conversation_repo

        thread_id, _ = edge_threads
        operator, user, received = await _connect_pair(live_server, thread_id)
        try:
            await operator.call(
                "takeover_conversation",
                {
                    "threadId": thread_id,
                    "tenantId": "nike",
                    "operatorId": f"op_edge_{_TS}",
                    "operatorName": "边缘测试坐席",
                },
                namespace=_NS,
                timeout=5,
            )
            await wait_for(
                lambda: any(
                    r["event"] == "conversation_state_changed"
                    and r["payload"].get("status") == "human_takeover"
                    for r in received
                )
            )

            await operator.disconnect()
            await wait_for(
                lambda: any(
                    r["event"] == "peer_disconnected" and r["payload"].get("role") == "operator"
                    for r in received
                )
            )

            # 断开 ≠ release:恢复 AI 托管必须是显式动作,状态保持 human_takeover
            timeline = await conversation_repo.get_conversation_timeline(thread_id, "nike")
            assert timeline["thread"]["status"] == "human_takeover"
            assert timeline["thread"]["assignedOperatorId"] == f"op_edge_{_TS}"
        finally:
            if operator.connected:
                await operator.disconnect()
            if user.connected:
                await user.disconnect()

    async def test_非法租户auth拒绝连接(self, live_server):
        r"""tenantId 空格/感叹号撞 _TENANT_RE(^[a-zA-Z0-9_-]{1,64}$)不匹配 → 服务端 connect 返回 False。

        客户端侧呈现两种皆可:connect 直接抛 ConnectionError,或返回但未连接。
        """
        import socketio as socketio_lib

        bad = socketio_lib.AsyncClient(reconnection=False)
        connected_ok = True
        try:
            await bad.connect(
                live_server,
                transports=["websocket"],
                namespaces=[_NS],
                auth={"tenantId": "bad tenant!", "userId": "u_edge_bad", "role": "user"},
            )
            connected_ok = bad.connected
        except Exception:
            connected_ok = False  # connect 阶段即抛(服务端拒绝的标准呈现)
        finally:
            if bad.connected:
                await bad.disconnect()
        assert not connected_ok

    async def test_send_message非法role落库归一为operator(self, live_server, edge_threads):
        from gateway_py import conversation_repo

        _, thread_id = edge_threads
        operator, user, received = await _connect_pair(live_server, thread_id)
        try:
            ack = await operator.call(
                "send_message",
                {
                    "threadId": thread_id,
                    "tenantId": "nike",
                    "role": "hacker",
                    "content": "边缘契约:白名单外 role",
                },
                namespace=_NS,
                timeout=5,
            )
            assert ack["success"] is True
            await wait_for(lambda: any(r["event"] == "new_message" for r in received))

            # 广播载荷透传原始 role(现状契约:房间回显原样),落库才归一
            broadcast = next(r for r in received if r["event"] == "new_message")
            assert broadcast["payload"]["role"] == "hacker"

            timeline = await conversation_repo.get_conversation_timeline(thread_id, "nike")
            saved = next(m for m in timeline["messages"] if m["id"] == ack["messageId"])
            assert saved["role"] == "operator"  # 白名单外 role 不得冒充 user/assistant/system
            assert saved["content"] == "边缘契约:白名单外 role"
        finally:
            if operator.connected:
                await operator.disconnect()
            if user.connected:
                await user.disconnect()


# ---------- 哨兵语义(repo 级,无需 socket) ----------


class TestUnsetSentinel:
    async def test_sentinel缺省保留坐席_显式None才清空(self, edge_threads):
        from gateway_py import conversation_repo

        _, thread_id = edge_threads

        taken = await conversation_repo.update_conversation_status(
            thread_id, "nike", "human_takeover", f"op_sentinel_{_TS}"
        )
        assert taken["status"] == "human_takeover"
        assert taken["assignedOperatorId"] == f"op_sentinel_{_TS}"

        # 缺省哨兵:纯状态变更(如 SPI close → resolved)不得顺手抹掉坐席归属
        resolved = await conversation_repo.update_conversation_status(thread_id, "nike", "resolved")
        assert resolved["status"] == "resolved"
        assert resolved["assignedOperatorId"] == f"op_sentinel_{_TS}"

        # 显式 None:release 语义,清空坐席字段
        released = await conversation_repo.update_conversation_status(thread_id, "nike", "active", None)
        assert released["status"] == "active"
        assert released["assignedOperatorId"] is None


if __name__ == "__main__":
    pytest.main([__file__])
