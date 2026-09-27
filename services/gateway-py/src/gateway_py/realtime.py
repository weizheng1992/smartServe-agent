"""实时接管网关 — 镜像 apps/server conversation.gateway(socket.io namespace /ws/chat 五事件)。

wire 协议 1:1:
- join_thread → joined_room(发给加入者) + peer_joined(房间广播)
- takeover_conversation / release_takeover → conversation_state_changed(含 systemMessage)
- send_message → new_message(含 id/timestamp) + ack {success, messageId}
- typing → user_typing(房间广播,排除发送者)
- 断开 → peer_disconnected

02 安全先行(2026-09-27)身份绑定:operator 连接必须持员工 JWT(connect auth.token,
租户须与员工行一致);坐席身份(operatorId/Name/operatorInfo)一律服务端派生,
客户端自报不再采信;员工连接仅能以 operator 身份发言,未认证连接仅能以 user
身份发言;事件租户须与 connect 租户一致。顾客 role=user 维持聊天弱身份模型。

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


async def _staff_from_token(token: str | None):
    """Bearer JWT → 在职员工(02 安全先行);缺/坏/登出 token 或非在职员工
    返回 None(socket 侧以拒绝连接呈现,非 HTTP 401)。接受裸 token 与
    Bearer 前缀两种形态(login data.token 为裸值)。"""
    raw = str(token or "").strip()
    if not raw:
        return None
    try:
        from engine_py.db import StaffMember, get_session
        from sqlalchemy import select

        from .routers.auth import require_claims

        claims = await require_claims(raw if raw.startswith("Bearer ") else f"Bearer {raw}")
        email = str(claims.get("email") or "")
        async with get_session() as session:
            staff = (
                await session.execute(select(StaffMember).where(StaffMember.email == email))
            ).scalars().first()
        if staff is None or staff.status != "enabled":
            return None
        return staff
    except Exception:
        return None


def _staff_of(sid: str) -> dict | None:
    """连接绑定的服务端坐席身份(connect 时由 JWT 派生);未认证连接为 None。"""
    return (connected_clients.get(sid) or {}).get("staff")


def _tenant_mismatch(sid: str, data: dict) -> bool:
    """事件租户必须与 connect 租户一致 —— 防同连接中途换租户join他商户房间。"""
    record = connected_clients.get(sid) or {}
    return str(data.get("tenantId") or "") != record.get("tenantId")


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
    record = {
        "threadId": auth.get("threadId"),
        "tenantId": clean_tenant,
        "role": auth.get("role", "user"),
    }
    # 02 安全先行(2026-09-27):operator 角色连接必须持有效员工 JWT,且员工
    # 租户与 connect tenantId 一致 —— 此前 operatorId/operatorName 全凭客户端
    # 自报,匿名可扮演任意坐席接管会话。顾客侧 role=user 维持聊天弱身份模型
    # (收口归 chat 面身份工作,另行立项)。当前线上无 socket 客户端,收紧免费。
    if record["role"] == "operator":
        staff = await _staff_from_token(auth.get("token"))
        if staff is None or staff.business_id != clean_tenant:
            return False
        record["staff"] = {
            "id": str(staff.id),
            "email": staff.email,
            "name": staff.display_name,
            "role": staff.role,
        }
    connected_clients[sid] = record
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
    if _tenant_mismatch(sid, data):
        return {"success": False, "error": "会话租户与连接租户不一致"}
    staff = _staff_of(sid)
    # 坐席展示身份一律服务端派生;未认证连接不得自报 operatorId/Name 冒充坐席
    operator_id = staff["email"] if staff else None
    operator_name = staff["name"] if staff else None
    room = _room(thread_id, tenant_id)
    connected_clients[sid] = {**connected_clients.get(sid, {}), "threadId": thread_id, "tenantId": tenant_id, "role": role}
    await sio.enter_room(sid, room, namespace=NAMESPACE)

    await sio.emit("joined_room", {"room": room, "threadId": thread_id, "tenantId": tenant_id}, to=sid, namespace=NAMESPACE)
    await sio.emit(
        "peer_joined",
        {
            "socketId": sid,
            "role": role,
            "operatorId": operator_id,
            "operatorName": operator_name,
            "timestamp": _dt.datetime.now().isoformat(),
        },
        room=room,
        namespace=NAMESPACE,
    )
    await _publish_ws_event("peer_joined", room, {"socketId": sid, "role": role, "operatorId": operator_id, "operatorName": operator_name})
    return {"success": True, "room": room, "threadId": thread_id, "tenantId": tenant_id}


@sio.on("takeover_conversation", namespace=NAMESPACE)
async def on_takeover(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    staff = _staff_of(sid)
    if staff is None:
        return {"success": False, "error": "坐席身份未认证,须以员工 JWT 建立 operator 连接"}
    if _tenant_mismatch(sid, data):
        return {"success": False, "error": "会话租户与坐席所属租户不一致"}
    # 服务端身份派生:客户端自报 operatorId/Name 不再采信(02 安全先行)
    operator_id, operator_name = staff["email"], staff["name"]

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
    if _staff_of(sid) is None:
        return {"success": False, "error": "坐席身份未认证,须以员工 JWT 建立 operator 连接"}
    if _tenant_mismatch(sid, data):
        return {"success": False, "error": "会话租户与坐席所属租户不一致"}
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
    content = data.get("content", "")
    cards = data.get("cards")
    staff = _staff_of(sid)
    if staff is not None:
        # 员工连接仅能以 operator 身份发言,坐席信息服务端派生 —— 此前客户端
        # 可自报任意 role(operator/assistant/system)伪造任意来源的时间线
        if str(data.get("role") or "operator") != "operator":
            return {"success": False, "error": "员工连接仅能以 operator 身份发言"}
        role = "operator"
        operator_info = {"operatorId": staff["email"], "operatorName": staff["name"]}
    else:
        # 未认证连接仅能以 user 身份发言(顾客 socket 通道;收口归 chat 面身份)
        if str(data.get("role") or "operator") != "user":
            return {"success": False, "error": "未认证连接仅能以 user 身份发言"}
        role = "user"
        operator_info = {}
    if _tenant_mismatch(sid, data):
        return {"success": False, "error": "会话租户与连接租户不一致"}

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
    if _tenant_mismatch(sid, data):
        return {"success": False, "error": "会话租户与连接租户不一致"}
    room = _room(thread_id, tenant_id)
    await sio.emit("user_typing", data, room=room, namespace=NAMESPACE, skip_sid=sid)
