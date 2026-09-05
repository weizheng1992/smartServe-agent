"""实时接管网关 — 镜像 apps/server conversation.gateway(socket.io namespace /ws/chat 五事件)。

wire 协议 1:1:
- join_thread → joined_room(发给加入者) + peer_joined(房间广播)
- takeover_conversation / release_takeover → conversation_state_changed(含 systemMessage)
- send_message → new_message(含 id/timestamp) + ack {success, messageId}
- typing → user_typing(房间广播,排除发送者)
- 断开 → peer_disconnected

发布侧沿用 Redis pub/sub 通道 ws:events(TS 现状:只发不收,消费方后续接入)。
"""

from __future__ import annotations

import datetime as _dt
import re

import socketio

from . import conversation_repo

NAMESPACE = "/ws/chat"
_TENANT_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*", namespaces=NAMESPACE)

# sid → {threadId, tenantId, role}
connected_clients: dict[str, dict] = {}


def _room(thread_id: str, tenant_id: str) -> str:
    return f"tenant:{tenant_id}:thread:{thread_id}"


async def _publish_ws_event(event: str, room: str, data) -> None:
    try:
        from engine_py.event_bus import get_client

        client = await get_client()
        if client is not None:
            import json

            await client.publish("ws:events", json.dumps({"event": event, "room": room, "data": data}, ensure_ascii=False, default=str))
    except Exception as err:
        print(f"[WS] Failed to publish redis ws event: {err}")


@sio.on("connect", namespace=NAMESPACE)
async def on_connect(sid: str, environ, auth=None):
    auth = auth or {}
    headers = dict(environ or {})
    query = auth
    raw_tenant = (
        auth.get("tenantId")
        or headers.get("HTTP_X_TENANT_ID")
        or headers.get("HTTP_X_BUSINESS_ID")
        or query.get("tenantId")
        or "ecommerce"
    )
    clean_tenant = str(raw_tenant).strip()
    if not _TENANT_RE.match(clean_tenant):
        return False  # 拒绝连接(镜像 TS client.disconnect(true))
    connected_clients[sid] = {
        "threadId": auth.get("threadId"),
        "tenantId": clean_tenant,
        "role": auth.get("role", "user"),
    }
    return True


@sio.on("disconnect", namespace=NAMESPACE)
async def on_disconnect(sid: str):
    info = connected_clients.pop(sid, None)
    if info and info.get("threadId") and info.get("tenantId"):
        room = _room(info["threadId"], info["tenantId"])
        await sio.emit(
            "peer_disconnected",
            {"socketId": sid, "role": info.get("role"), "timestamp": _dt.datetime.now().isoformat()},
            room=room,
            namespace=NAMESPACE,
        )


@sio.on("join_thread", namespace=NAMESPACE)
async def on_join_thread(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    role = data.get("role", "user")
    room = _room(thread_id, tenant_id)
    connected_clients[sid] = {**connected_clients.get(sid, {}), "threadId": thread_id, "tenantId": tenant_id, "role": role}
    await sio.enter_room(sid, room, namespace=NAMESPACE)

    await sio.emit("joined_room", {"room": room, "threadId": thread_id, "tenantId": tenant_id}, to=sid, namespace=NAMESPACE)
    await sio.emit(
        "peer_joined",
        {
            "socketId": sid,
            "role": role,
            "operatorId": data.get("operatorId"),
            "operatorName": data.get("operatorName"),
            "timestamp": _dt.datetime.now().isoformat(),
        },
        room=room,
        namespace=NAMESPACE,
    )
    await _publish_ws_event("peer_joined", room, {"socketId": sid, "role": role, "operatorId": data.get("operatorId"), "operatorName": data.get("operatorName")})
    return {"success": True, "room": room, "threadId": thread_id, "tenantId": tenant_id}


@sio.on("takeover_conversation", namespace=NAMESPACE)
async def on_takeover(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    operator_id = data.get("operatorId", "")
    operator_name = data.get("operatorName", "")

    await conversation_repo.update_conversation_status(thread_id, tenant_id, "human_takeover", operator_id)
    sys_msg = await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": tenant_id,
            "role": "system",
            "content": f"人工客服【{operator_name}】已接入会话，AI 智能体已暂停托管。",
            "operatorInfo": {"operatorId": operator_id, "operatorName": operator_name},
        }
    )
    room = _room(thread_id, tenant_id)
    await sio.emit(
        "conversation_state_changed",
        {
            "threadId": thread_id,
            "status": "human_takeover",
            "operatorId": operator_id,
            "operatorName": operator_name,
            "systemMessage": sys_msg,
        },
        room=room,
        namespace=NAMESPACE,
    )
    await _publish_ws_event(
        "conversation_state_changed", room, {"threadId": thread_id, "status": "human_takeover", "operatorId": operator_id, "operatorName": operator_name}
    )
    return {"success": True, "status": "human_takeover"}


@sio.on("release_takeover", namespace=NAMESPACE)
async def on_release_takeover(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    await conversation_repo.update_conversation_status(thread_id, tenant_id, "active", None)
    sys_msg = await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": tenant_id,
            "role": "system",
            "content": "人工客服已结束接管，已重新切换为 AI 智能助手为您服务。",
        }
    )
    room = _room(thread_id, tenant_id)
    await sio.emit(
        "conversation_state_changed",
        {"threadId": thread_id, "status": "active", "systemMessage": sys_msg},
        room=room,
        namespace=NAMESPACE,
    )
    await _publish_ws_event("conversation_state_changed", room, {"threadId": thread_id, "status": "active"})
    return {"success": True, "status": "active"}


@sio.on("send_message", namespace=NAMESPACE)
async def on_send_message(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    role = data.get("role", "operator")
    content = data.get("content", "")
    cards = data.get("cards")
    operator_info = data.get("operatorInfo") or {}

    saved = await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": tenant_id,
            "role": role if role in ("user", "assistant", "system", "operator") else "operator",
            "content": content,
            "cards": cards,
            "operatorInfo": operator_info,
        }
    )
    room = _room(thread_id, tenant_id)
    msg_payload = {
        "id": saved["id"],
        "threadId": thread_id,
        "tenantId": tenant_id,
        "role": role,
        "content": content,
        "cards": cards,
        "operatorInfo": operator_info,
        "timestamp": saved.get("timestamp"),
    }
    await sio.emit("new_message", msg_payload, room=room, namespace=NAMESPACE)
    await _publish_ws_event("new_message", room, msg_payload)
    return {"success": True, "messageId": saved["id"]}


@sio.on("typing", namespace=NAMESPACE)
async def on_typing(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    room = _room(thread_id, tenant_id)
    await sio.emit("user_typing", data, room=room, namespace=NAMESPACE, skip_sid=sid)
