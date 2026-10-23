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


async def broadcast_customer_message(thread_id: str, tenant_id: str, saved: dict, content: str) -> None:
    """顾客 HTTP 消息 → 坐席 socket 房间桥(2026-10-23 线上「接管后顾客消息坐席
    不再看到」收口)。

    坐席台开着的线程面板只靠 new_message 刷新(use-live-desk);顾客消息经
    POST /api/chat / POST /api/store/chat(HTTP 面,顾客端零 socket 客户端)落库,
    此前从不进坐席房间 —— 接管会话中坐席只看得到自己发言,顾客后续消息全部
    静默(线上实弹:unread_count 堆到 8,刷新才见)。本桥挂在两表面共用的受理脊
    chat_turn.accept_chat_turn 落库点,paused/常规两臂均覆盖。

    镜像 2026-09-29 坐席→顾客桥(send_message 侧补 publish_thread_message);
    顾客 SSE 频道(thread:{id}:message)刻意**不**补发 user 帧 —— 顾客端对自有
    消息乐观呈现,补发双气泡(乐观 id ≠ 服务端 id,按 id 去重不命中)。"""
    room = _room(thread_id, tenant_id)
    payload = {
        "id": saved["id"],
        "threadId": thread_id,
        "tenantId": tenant_id,
        "role": "user",
        "content": content,
        "cards": None,
        "operatorInfo": {},
        "timestamp": saved.get("timestamp"),
    }
    await sio.emit("new_message", payload, room=room, namespace=NAMESPACE)
    await _publish_ws_event("new_message", room, payload)


async def _staff_from_token(token: str | None):
    """Bearer JWT → 在职员工(02 安全先行);缺/坏/登出 token 或非在职员工
    返回 None(socket 侧以拒绝连接呈现,非 HTTP 401)。接受裸 token 与
    Bearer 前缀两种形态(login data.token 为裸值)。

    身份解析上收 tenant_scope.resolve_staff(架构审查 #5)—— 此前 socket 侧
    手搓 JWT→staff 查库是坐席身份 adapter 的第三份抄本。"""
    from .tenant_scope import resolve_staff

    raw = str(token or "").strip()
    if not raw:
        return None
    try:
        identity = await resolve_staff(raw if raw.startswith("Bearer ") else f"Bearer {raw}")
        return identity.staff if identity is not None else None
    except Exception:
        return None


def _staff_of(sid: str) -> dict | None:
    """连接绑定的服务端坐席身份(connect 时由 JWT 派生);未认证连接为 None。"""
    return (connected_clients.get(sid) or {}).get("staff")


async def _has_operate_perm(tenant_id: str, staff: dict) -> bool:
    """live_desk:operate 闸(live-desk-rework §2.2):接管/发言/释放三路坐席
    动作逐路校验。判定上收 tenant_scope.has_perm(fail-closed 单点,架构审查 #5)。"""
    from .tenant_scope import has_perm

    return await has_perm(tenant_id, str(staff.get("role") or ""), "live_desk:operate")


async def _append_takeover_system_message(
    thread_id: str, tenant_id: str, content: str, operator: dict | None = None
) -> dict:
    """接管期系统消息 + 顾客侧桥(single point):落库 role=system 并同步发布
    thread:{id}:message 顾客 SSE —— on_takeover / on_release_takeover 两处
    逐行同构的编排收拢于此。"""
    msg = await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": tenant_id,
            "role": "system",
            "content": content,
            **({"operatorInfo": operator} if operator else {}),
        }
    )
    await conversation_repo.publish_thread_message(thread_id, msg)
    return msg


async def _broadcast_state_changed(
    thread_id: str,
    tenant_id: str,
    *,
    operator: dict | None = None,
    system_message: dict | None = None,
) -> dict:
    """状态变更双通道广播(socket 房间 + ws:events)single point。

    线形状:socket 载荷可含 systemMessage;ws:events 恒不含(与历史一致)。"""
    state = await takeover.thread_state(thread_id)
    room = _room(thread_id, tenant_id)
    payload = {"threadId": thread_id, **state}
    if operator is not None:
        payload["operatorId"] = operator.get("email")
        payload["operatorName"] = operator.get("name")
    if system_message is not None:
        payload["systemMessage"] = system_message
    await sio.emit("conversation_state_changed", payload, room=room, namespace=NAMESPACE)
    await _publish_ws_event(
        "conversation_state_changed",
        room,
        {k: v for k, v in payload.items() if k != "systemMessage"},
    )
    return state


def _tenant_mismatch(sid: str, data: dict) -> bool:
    """事件租户必须与 connect 租户一致 —— 防同连接中途换租户join他商户房间。"""
    record = connected_clients.get(sid) or {}
    return str(data.get("tenantId") or "") != record.get("tenantId")


def _connect_user_id(sid: str) -> str:
    """connect 握手自报的顾客 userId(弱身份模型在案);operator 连接不用此值。"""
    return str((connected_clients.get(sid) or {}).get("userId") or "")


async def _user_thread_guard(thread_id: str, tenant_id: str, user_id: str) -> str | None:
    """user 侧线程属主闸(2026-10-17 窃听族收口):线程必须存在、租户须一致、
    有主线程必须 connect userId 精确等值 —— 顾客弱身份模型下,此闸令「猜线程
    id 听/写他会话」失效(攻击者还须知道受害者 userId)。None=通过,否则拒绝
    文案。无主线程(user_id NULL)放行:无从属主保护,兼容存量。operator 连接
    不走此闸(JWT+operate 权限已是其闸)。"""
    ownership = await conversation_repo.thread_ownership(thread_id)
    if ownership is None:
        return "会话不存在"
    owner_tenant = str(ownership.get("business_id") or "")
    if owner_tenant and owner_tenant != tenant_id:
        return "会话不属于该商户"
    owner_user = str(ownership.get("user_id") or "")
    if owner_user and owner_user != user_id:
        return "会话不属于当前用户"
    return None


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
        # 顾客 userId 在 connect 握手一次绑定(join/send 的属主闸只认握手值,
        # 事件内自报不再采信 —— 防同连接中途换 userId 入他人线程)
        "userId": str(auth.get("userId") or ""),
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
            {"socketId": sid, "role": info.get("role"), "timestamp": _dt.datetime.now(_dt.UTC).isoformat()},
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
    # user 侧属主闸(2026-10-17 窃听族收口):匿名连接此前凭猜到的 threadId 即
    # 可入任意房间听会话全文(new_message 含 content)。operator 不走此闸。
    if staff is None:
        err = await _user_thread_guard(thread_id, tenant_id, _connect_user_id(sid))
        if err:
            return {"success": False, "error": err}
    # 坐席展示身份一律服务端派生;未认证连接不得自报 operatorId/Name 冒充坐席
    operator_id = staff["email"] if staff else None
    operator_name = staff["name"] if staff else None
    # 换房先退旧房:入房不退房会让切线程后的连接继续收旧房 new_message(残留窃听面)
    prev = connected_clients.get(sid) or {}
    if prev.get("threadId") and prev.get("tenantId"):
        await sio.leave_room(sid, _room(prev["threadId"], prev["tenantId"]), namespace=NAMESPACE)
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
            "timestamp": _dt.datetime.now(_dt.UTC).isoformat(),
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
    # 系统消息不广播。系统消息/顾客桥/双通道广播编排收拢于本文件 helper。
    claimed = await takeover.assign_operator(thread_id, operator_id, business_id=tenant_id)
    if not claimed:
        return {"success": False, "error": "会话已被其他坐席认领"}
    sys_msg = await _append_takeover_system_message(
        thread_id,
        tenant_id,
        f"人工客服【{operator_name}】已接入会话，AI 智能体已暂停托管。",
        operator={"operatorId": operator_id, "operatorName": operator_name},
    )
    state = await _broadcast_state_changed(
        thread_id, tenant_id, operator={"email": operator_id, "name": operator_name}, system_message=sys_msg
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
    sys_msg = await _append_takeover_system_message(
        thread_id, tenant_id, "人工客服已结束接管，已重新切换为 AI 智能助手为您服务。"
    )
    state = await _broadcast_state_changed(thread_id, tenant_id, system_message=sys_msg)
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
        # user 侧属主闸(与 join_thread 同律):严禁借 socket 通道往他人线程写
        err = await _user_thread_guard(thread_id, tenant_id, _connect_user_id(sid))
        if err:
            return {"success": False, "error": err}
        role = "user"
        operator_info = {}
    if _tenant_mismatch(sid, data):
        return {"success": False, "error": "会话租户与连接租户不一致"}

    # 认领闸(2026-09-29 实弹):坐席发言路对齐认领池守卫 —— 未接管会话禁言
    # (AI 托管中直插真人发言,顾客端真人/AI 各说各话);呼叫中(接管态+坐席空)
    # 首发即原子认领(与认领按钮同一 assign_operator 守卫,两坐席同抢只成一人,
    # 败者收「已被认领」);已被他人认领则拒绝。坐席台 sendMessage 不先点接管,
    # 发言即认领保证 UX 不断。顾客 role=user 不设闸(弱身份模型)。
    if role == "operator":
        state = await takeover.thread_state(thread_id)
        if state.get("status") != "human_takeover":
            return {"success": False, "error": "会话未被接管：请先认领会话后再发言"}
        assigned = state.get("assignedOperatorId")
        if assigned and assigned != staff["email"]:
            return {"success": False, "error": "会话已被其他坐席认领，无法发言"}
        if not assigned:
            if not await takeover.assign_operator(thread_id, staff["email"], business_id=tenant_id):
                return {"success": False, "error": "会话已被其他坐席认领，无法发言"}
            # 广播认领结果:其他坐席的会话列表据 conversation_state_changed
            # 就地对齐(use-live-desk 认领/释放广播同通道),呼叫中行不滞留
            await _broadcast_state_changed(
                thread_id, tenant_id, operator={"email": staff["email"], "name": staff["name"]}
            )

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
