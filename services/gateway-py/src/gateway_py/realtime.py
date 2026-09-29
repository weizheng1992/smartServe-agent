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
from engine_py.approvals import presence, takeover
from engine_py.config import settings

from . import conversation_repo

NAMESPACE = "/ws/chat"
_TENANT_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
# P4 消息幂等(live-desk-rework spec §2.7):客户端去重键 = UUID/雪花形短标识,
# 透传 messages.id;ON CONFLICT DO NOTHING 重放静默,ack 回既有 id。非法值
# (空/超长/奇异字符)忽略回落服务端 uuid4,幂等退化为无键直写。
_CLIENT_MSG_ID_RE = re.compile(r"^[0-9a-zA-Z-]{8,64}$")

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


async def _has_operate_perm(tenant_id: str, staff: dict) -> bool:
    """live_desk:operate 闸(live-desk-rework §2.2,照 order:ship 的
    perms_for_role 先例):接管/发言/释放三路坐席动作逐路校验;权限点按员工
    真租户的角色菜单闭包判定,角色管理页勾选即生效。租户即 connect 时与
    staff.business_id 校验一致的 tenantId。"""
    from engine_py.analytics import rbac

    try:
        return "live_desk:operate" in await rbac.perms_for_role(tenant_id, str(staff.get("role") or ""))
    except Exception as err:
        print(f"[Realtime] perm 判定失败(按无权限处理): {err}")
        return False


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
        # P2 在线态(spec §2.3):连接态即在线 —— 坐席 connect 即点亮 presence
        # (Redis TTL 心跳;仅展示,不作分配闸),后续 join/ping/发言续期
        try:
            await presence.heartbeat(clean_tenant, staff.email)
        except Exception as err:
            print(f"[Realtime] presence 心跳失败(不阻断连接): {err}")
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
    # P1 掉线超时释放(live-desk-rework spec §2.1):坐席掉线给其名下全部接管
    # 会话写 DB 释放 deadline;权威释放由 engine scheduler 幂等扫描执行
    # (多实例约束:进程内计时器仅可作 UX 提示,spec §6)。重连(join/认领/
    # 发言)即取消。P1 前端零 socket,机制先钉契约,P2 坐席面接入后全面生效。
    operator_email = (info or {}).get("staff", {}).get("email")
    if operator_email and info.get("tenantId"):
        try:
            await presence.drop(info["tenantId"], operator_email)
        except Exception as err:
            print(f"[Realtime] presence 离线失败(不阻断断线流程): {err}")
    if operator_email:
        try:
            n = await takeover.mark_disconnect_deadlines(operator_email, settings.takeover_release_timeout_seconds)
            if n:
                print(f"[Realtime] 坐席 {operator_email} 掉线,已对 {n} 个接管会话写释放计时({settings.takeover_release_timeout_seconds:.0f}s)")
        except Exception as err:
            print(f"[Realtime] 释放计时写入失败(不阻断断线流程): {err}")


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

    # P1:坐席加入房间 = 重连/在岗信号,取消其名下接管会话的掉线释放计时;
    # P2:同信号续期 presence 心跳
    if staff is not None:
        try:
            await takeover.cancel_disconnect_deadlines(staff["email"])
        except Exception as err:
            print(f"[Realtime] 释放计时取消失败(不阻断入房): {err}")
        try:
            await presence.heartbeat(tenant_id, staff["email"])
        except Exception as err:
            print(f"[Realtime] presence 心跳失败(不阻断入房): {err}")

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
    if not await _has_operate_perm(tenant_id, staff):
        return {"success": False, "error": "无坐席操作权限(live_desk:operate)"}
    # 服务端身份派生:客户端自报 operatorId/Name 不再采信(02 安全先行)
    operator_id, operator_name = staff["email"], staff["name"]

    # P1 真源归一 + P2 认领池原子守卫(spec §2.3):认领即清掉线释放计时;
    # business_id 收租户 WHERE。两坐席同抢只成一人,败者收「已被认领」且不落
    # 系统消息不广播。
    claimed = await takeover.assign_operator(thread_id, operator_id, business_id=tenant_id)
    if not claimed:
        return {"success": False, "error": "会话已被其他坐席认领"}
    sys_msg = await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": tenant_id,
            "role": "system",
            "content": f"人工客服【{operator_name}】已接入会话，AI 智能体已暂停托管。",
            "operatorInfo": {"operatorId": operator_id, "operatorName": operator_name},
        }
    )
    # 顾客侧桥:接入通知同步送达顾客 SSE(顾客须知道对面已换成真人)
    await conversation_repo.publish_thread_message(thread_id, sys_msg)
    state = await takeover.thread_state(thread_id)
    room = _room(thread_id, tenant_id)
    await sio.emit(
        "conversation_state_changed",
        {
            "threadId": thread_id,
            **state,
            "operatorId": operator_id,
            "operatorName": operator_name,
            "systemMessage": sys_msg,
        },
        room=room,
        namespace=NAMESPACE,
    )
    await _publish_ws_event(
        "conversation_state_changed",
        room,
        {"threadId": thread_id, **state, "operatorId": operator_id, "operatorName": operator_name},
    )
    return {"success": True, "status": "human_takeover", **state}


@sio.on("release_takeover", namespace=NAMESPACE)
async def on_release_takeover(sid: str, data: dict):
    thread_id = data.get("threadId", "")
    tenant_id = data.get("tenantId", "")
    staff = _staff_of(sid)
    if staff is None:
        return {"success": False, "error": "坐席身份未认证,须以员工 JWT 建立 operator 连接"}
    if _tenant_mismatch(sid, data):
        return {"success": False, "error": "会话租户与坐席所属租户不一致"}
    if not await _has_operate_perm(tenant_id, staff):
        return {"success": False, "error": "无坐席操作权限(live_desk:operate)"}
    # P1 真源归一:释放条件 UPDATE 幂等(重复释放不重复落系统消息);
    # business_id 收租户 WHERE,严防跨租户释放。
    await takeover.release_takeover(thread_id, business_id=tenant_id)
    sys_msg = await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": tenant_id,
            "role": "system",
            "content": "人工客服已结束接管，已重新切换为 AI 智能助手为您服务。",
        }
    )
    # 顾客侧桥:释放通知同步送达顾客 SSE
    await conversation_repo.publish_thread_message(thread_id, sys_msg)
    state = await takeover.thread_state(thread_id)
    room = _room(thread_id, tenant_id)
    await sio.emit(
        "conversation_state_changed",
        {"threadId": thread_id, **state, "systemMessage": sys_msg},
        room=room,
        namespace=NAMESPACE,
    )
    await _publish_ws_event("conversation_state_changed", room, {"threadId": thread_id, **state})
    return {"success": True, "status": "active", **state}


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
        if not await _has_operate_perm(tenant_id, staff):
            return {"success": False, "error": "无坐席操作权限(live_desk:operate)"}
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

    # P4 消息幂等(spec §2.7):clientMsgId 合法即透传为消息主键 —— 重发/断线
    # 重连重放经 append_message 的 ON CONFLICT DO NOTHING 静默去重,ack 仍回
    # 既有 id,前端据以对齐乐观气泡(重放不产生第二条时间线行)。
    client_msg_id = str(data.get("clientMsgId") or "").strip()
    if not _CLIENT_MSG_ID_RE.fullmatch(client_msg_id):
        client_msg_id = ""
    saved = await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": tenant_id,
            "role": role if role in ("user", "assistant", "system", "operator") else "operator",
            "content": content,
            "cards": cards,
            "operatorInfo": operator_info,
            **({"id": client_msg_id} if client_msg_id else {}),
        }
    )
    # 顾客侧桥(2026-09-29 实弹修复):坐席消息同步发布 thread:{id}:message,
    # 商户商城 SSE(/api/store/chat/stream)才能实时送达 —— 此前只走 socket
    # 房间 + ws:events(无消费方),顾客端无 socket.io 客户端,坐席「已接管」
    # 顾客仍只见「?」。仅桥 operator:顾客自有消息已在端上乐观呈现,补发反致
    # 双气泡(乐观 id ≠ 服务端 id,按 id 去重不命中)。
    if role == "operator":
        await conversation_repo.publish_thread_message(
            thread_id,
            {
                "id": saved["id"],
                "threadId": thread_id,
                "role": role,
                "content": content,
                "cards": cards,
                "operatorInfo": operator_info,
                "timestamp": saved.get("timestamp"),
            },
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


@sio.on("presence_ping", namespace=NAMESPACE)
async def on_presence_ping(sid: str, data: dict | None = None):
    """P2 在线态心跳(空闲坐席保活;spec §2.3 TTL 心跳)。仅认证坐席生效。"""
    staff = _staff_of(sid)
    if staff is None:
        return {"success": False, "error": "坐席身份未认证"}
    tenant_id = (connected_clients.get(sid) or {}).get("tenantId") or ""
    try:
        await presence.heartbeat(tenant_id, staff["email"])
    except Exception as err:
        print(f"[Realtime] presence 心跳失败: {err}")
        return {"success": False, "error": "presence 暂不可用"}
    return {"success": True}


@sio.on("presence_dnd", namespace=NAMESPACE)
async def on_presence_dnd(sid: str, data: dict):
    """P2 手动免打扰自拨(socket 通道;HTTP /api/merchant/live-desk/presence/dnd
    同语义)。仅改自己的开关。"""
    staff = _staff_of(sid)
    if staff is None:
        return {"success": False, "error": "坐席身份未认证"}
    tenant_id = (connected_clients.get(sid) or {}).get("tenantId") or ""
    enabled = bool((data or {}).get("enabled"))
    try:
        await presence.set_dnd(tenant_id, staff["email"], enabled)
    except Exception as err:
        print(f"[Realtime] presence 免打扰失败: {err}")
        return {"success": False, "error": "presence 暂不可用"}
    return {"success": True, "dnd": enabled}
