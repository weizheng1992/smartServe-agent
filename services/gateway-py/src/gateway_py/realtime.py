"""实时接管网关 — 镜像 conversation.gateway(socket.io namespace /ws/chat 五事件)。

进程内连接表 + 内存 rooms(与 TS 版一致的单实例约束);
发布侧沿用 Redis pub/sub 通道 ws:events(TS 现状:只发不收,消费方后续接入)。
"""

from __future__ import annotations

import socketio

from .. import conversation_repo

NAMESPACE = "/ws/chat"

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*", namespaces=NAMESPACE)

# sid → {threadId, tenantId, role}
connected_clients: dict[str, dict] = {}


def _room(thread_id: str, tenant_id: str) -> str:
    return f"tenant:{tenant_id}:thread:{thread_id}"


@sio.on("connect", namespace=NAMESPACE)
async def on_connect(sid: str, environ, auth=None):
    auth = auth or {}
    connected_clients[sid] = {
        "threadId": auth.get("threadId"),
        "tenantId": auth.get("tenantId"),
        "role": auth.get("role", "user"),
    }
    return True


@sio.on("disconnect", namespace=NAMESPACE)
async def on_disconnect(sid: str):
    info = connected_clients.pop(sid, None)
    if info and info.get("threadId"):
        room = _room(info["threadId"], info.get("tenantId") or "")
        await sio.emit("peer_disconnected", {"sid": sid, **{k: v for k, v in info.items() if v}}, room=room, namespace=NAMESPACE)


@sio.on("join_thread", namespace=NAMESPACE)
async def on_join_thread(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    room = _room(thread_id, tenant_id)
    connected_clients[sid] = {**connected_clients.get(sid, {}), "threadId": thread_id, "tenantId": tenant_id, "role": data.get("role", "user")}
    await sio.enter_room(sid, room, namespace=NAMESPACE)
    await sio.emit(
        "peer_joined",
        {"sid": sid, "threadId": thread_id, "tenantId": tenant_id, "role": data.get("role", "user")},
        room=room,
        namespace=NAMESPACE,
    )
    return {"success": True, "room": room, "threadId": thread_id, "tenantId": tenant_id}


@sio.on("takeover_conversation", namespace=NAMESPACE)
async def on_takeover(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    operator_id = data.get("operatorId", "")
    operator_name = data.get("operatorName", "")

    await conversation_repo.update_conversation_status(thread_id, tenant_id, "human_takeover", operator_id)
    room = _room(thread_id, tenant_id)
    await sio.emit(
        "conversation_state_changed",
        {
            "threadId": thread_id,
            "tenantId": tenant_id,
            "status": "human_takeover",
            "operatorId": operator_id,
            "operatorName": operator_name,
        },
        room=room,
        namespace=NAMESPACE,
    )
    return {"success": True, "status": "human_takeover"}


@sio.on("release_takeover", namespace=NAMESPACE)
async def on_release_takeover(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    await conversation_repo.update_conversation_status(thread_id, tenant_id, "active")
    room = _room(thread_id, tenant_id)
    await sio.emit(
        "conversation_state_changed",
        {"threadId": thread_id, "tenantId": tenant_id, "status": "active"},
        room=room,
        namespace=NAMESPACE,
    )
    return {"success": True, "status": "active"}


@sio.on("send_message", namespace=NAMESPACE)
async def on_send_message(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    role = data.get("role", "operator")
    content = data.get("content", "")
    operator_info = data.get("operatorInfo") or {}

    await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": tenant_id,
            "role": role if role in ("user", "assistant", "system", "operator") else "operator",
            "content": content,
            "operatorInfo": operator_info,
        }
    )
    room = _room(thread_id, tenant_id)
    msg_payload = {
        "threadId": thread_id,
        "tenantId": tenant_id,
        "role": role,
        "content": content,
        "operatorInfo": operator_info,
    }
    await sio.emit("new_message", msg_payload, room=room, namespace=NAMESPACE)
    return {"success": True, "message": msg_payload}


@sio.on("typing", namespace=NAMESPACE)
async def on_typing(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    payload = {**data, "sid": sid}
    await sio.emit("user_typing", payload, room=_room(thread_id, tenant_id), namespace=NAMESPACE)
    return {"success": True}
