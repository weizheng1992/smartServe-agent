"""会话仓储 — 镜像 packages/db/src/services/conversationRepository.ts。"""

from __future__ import annotations

import datetime as _dt
import json
import uuid

from engine_py.db import get_session
from sqlalchemy import text

# 顾客侧实时频道(store SSE /api/store/chat/stream 订阅转发,商户商城顾客端
# 唯一实时耳朵)。坐席/系统消息落库后必须桥接此频道,见 publish_thread_message。
THREAD_CHANNEL = "thread:{thread_id}:message"


async def list_conversations(
    business_id: str,
    user_id: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    search_keyword: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    clean_biz_id = (business_id or "").lower().strip()
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    conditions: list[str] = []
    params: dict = {}
    if clean_biz_id and clean_biz_id != "all":
        conditions.append("t.business_id = :bid")
        params["bid"] = clean_biz_id
    if user_id and user_id.strip():
        u = user_id.strip()
        conditions.append("(t.user_id = :u1 OR t.id ILIKE :u2)")
        params["u1"] = u
        params["u2"] = f"%{u}%"
    if status and status != "all":
        conditions.append("t.status = :status")
        params["status"] = status
    if tag:
        conditions.append("t.tags @> CAST(:tag AS jsonb)")
        params["tag"] = json.dumps([tag])
    if search_keyword and search_keyword.strip():
        keyword = f"%{search_keyword.strip()}%"
        conditions.append(
            "(t.id ILIKE :kw OR EXISTS (SELECT 1 FROM messages m WHERE m.thread_id = t.id AND m.content ILIKE :kw))"
        )
        params["kw"] = keyword
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with get_session() as session:
        total = (
            await session.execute(text(f"SELECT COUNT(*) AS count FROM threads t {where_clause}").bindparams(**params))
        ).mappings().first()["count"]

        rows = (
            (
                await session.execute(
                    text(
                        "SELECT t.id AS thread_id, t.business_id, t.user_id, t.status, t.assigned_operator_id, "
                        "COALESCE(t.unread_count, 0) AS unread_count, COALESCE(t.tags, '[]'::jsonb) AS tags, "
                        "COALESCE(t.metadata, '{}'::jsonb) AS metadata, t.created_at, t.updated_at, "
                        "m.content AS last_msg_content, m.role AS last_msg_role, m.timestamp AS last_msg_time, "
                        "COALESCE(mc.msg_count, 0) AS msg_count, "
                        "COALESCE(lm.total_tokens, 0) AS total_tokens, "
                        "COALESCE(lm.cost_usd, 0) AS cost_usd, "
                        "COALESCE(lm.llm_calls, 0) AS llm_calls "
                        "FROM threads t LEFT JOIN LATERAL ("
                        "  SELECT content, role, timestamp FROM messages WHERE thread_id = t.id "
                        "  ORDER BY created_at DESC, timestamp DESC LIMIT 1"
                        ") m ON true "
                        # 会话级真实遥测(2026-09-13 real-data-only):此前前端对缺失字段
                        # 兜底 850 tokens / $0.0035 / 1 条消息等编造值,全部改为库内真算
                        "LEFT JOIN LATERAL ("
                        "  SELECT COUNT(*) AS msg_count FROM messages m2 WHERE m2.thread_id = t.id"
                        ") mc ON true "
                        "LEFT JOIN LATERAL ("
                        "  SELECT COALESCE(SUM(COALESCE(l.tokens_in, 0) + COALESCE(l.tokens_out, 0)), 0) AS total_tokens, "
                        "  COALESCE(SUM(l.cost_usd), 0) AS cost_usd, "
                        "  COUNT(*) AS llm_calls "
                        "  FROM llm_call_logs l WHERE l.thread_id = t.id"
                        ") lm ON true "
                        f"{where_clause} ORDER BY t.updated_at DESC LIMIT :lim OFFSET :off"
                    ).bindparams(**params, lim=limit, off=offset)
                )
            )
            .mappings()
            .all()
        )

    items = []
    for r in rows:
        snippet = r["last_msg_content"]
        if snippet and len(snippet) > 80:
            snippet = snippet[:80] + "..."
        items.append(
            {
                "threadId": r["thread_id"],
                "businessId": r["business_id"],
                "userId": r["user_id"],
                "status": r["status"] or "active",
                "assignedOperatorId": r["assigned_operator_id"],
                "unreadCount": r["unread_count"],
                "tags": r["tags"] if isinstance(r["tags"], list) else [],
                "metadata": r["metadata"] or {},
                "createdAt": r["created_at"].isoformat() if r["created_at"] else _dt.datetime.now().isoformat(),
                "updatedAt": r["updated_at"].isoformat() if r["updated_at"] else _dt.datetime.now().isoformat(),
                "lastMessageSnippet": snippet,
                "lastMessageRole": r["last_msg_role"],
                "lastMessageTime": r["last_msg_time"],
                # 会话级真实遥测(llm_call_logs / messages 库内真算,无命中即 0)
                "messageCount": int(r["msg_count"]),
                "totalTokens": int(r["total_tokens"]),
                "costUsd": float(r["cost_usd"]),
                "llmCalls": int(r["llm_calls"]),
            }
        )
    return {"items": items, "total": int(total)}


async def get_conversation_timeline(thread_id: str, business_id: str | None = None) -> dict | None:
    clean_thread_id = thread_id.strip()
    clean_biz_id = (business_id or "").lower().strip()

    async with get_session() as session:
        thread_row = (
            await session.execute(text("SELECT * FROM threads WHERE id = :tid").bindparams(tid=clean_thread_id))
        ).mappings().first()
        if not thread_row:
            return None

        actual_biz_id = str(thread_row["business_id"] or "ecommerce").lower()
        # 🛡️ 多租户身份校验(自愈收口 2026-10-02 code-review):跨租户一律隔离
        # 为空,严禁改判归属、不落任何 UPDATE。旧「自愈补全(镜像 TS 逻辑)」的
        # 两条改判路径 —— actual=='ecommerce' 图章认领、租户名是 threadId 子串
        # 认领 —— 都是夺权面:拿他租线程 id 请求即可把会话改判到自己名下并整段
        # 读出(header+猜名)。threads.business_id 本就 NOT NULL(models.py:46),
        # 「无主认领」无从发生;建线程 upsert 的「无主线程自愈认领」是
        # chat.py 的另一条路径,不受此处收口影响。
        if clean_biz_id and clean_biz_id != "all":
            if actual_biz_id != clean_biz_id:
                return None  # 跨租户访问 → 隔离为空

        messages = (
            (
                await session.execute(
                    text(
                        # 排序锚用 created_at 而非 TEXT 列 timestamp:网关写 naive 本地墙钟、
                        # 引擎写 UTC(带偏移的模拟时钟),两格式字符串比较无意义 —— 曾致
                        # 「用户问→客服答」跨格式倒置(答在问上)。created_at 为 DB 单一
                        # 时钟(DEFAULT now()),与 list_conversations / list_user_threads
                        # LATERAL 末消息选取(ORDER BY created_at DESC)同锚;role 位次
                        # 保留同刻并列时的逻辑序(同事务 now() 相同:先问后答)。
                        "SELECT id, role, content, cards, image_urls, timestamp FROM messages WHERE thread_id = :tid "
                        "ORDER BY created_at ASC, CASE role WHEN 'system' THEN 1 WHEN 'user' THEN 2 "
                        "WHEN 'assistant' THEN 3 ELSE 4 END ASC, id ASC"
                    ).bindparams(tid=clean_thread_id)
                )
            )
            .mappings()
            .all()
        )

    parsed_messages = []
    for m in messages:
        cards = m["cards"]
        if isinstance(cards, str):
            try:
                cards = json.loads(cards)
            except Exception:
                cards = None
        parsed_messages.append(
            {
                "id": str(m["id"]),
                "role": m["role"],
                "content": m["content"],
                "cards": cards,
                "imageUrls": m["image_urls"] if isinstance(m["image_urls"], list) else None,
                "timestamp": m["timestamp"],
            }
        )

    return {
        "thread": {
            "threadId": thread_row["id"],
            "businessId": actual_biz_id,
            "userId": thread_row["user_id"],
            "status": thread_row["status"] or "active",
            "assignedOperatorId": thread_row["assigned_operator_id"],
            "unreadCount": thread_row["unread_count"] or 0,
            "tags": thread_row["tags"] if isinstance(thread_row["tags"], list) else [],
            "createdAt": thread_row["created_at"].isoformat() if thread_row["created_at"] else None,
            "updatedAt": thread_row["updated_at"].isoformat() if thread_row["updated_at"] else None,
        },
        "messages": parsed_messages,
    }


async def update_conversation_status(
    thread_id: str,
    business_id: str,
    status: str,
    assigned_operator_id: object = "__unset__",
    tags: list | None = None,
) -> dict | None:
    """状态更新(接管不变量内嵌,架构审查 #5):本 repo 是 threads.status 的
    唯一写入口 —— 任何把 human_takeover 线程改走的状态写(管理台任意值透传 /
    SPI close)在此自动清除接管元数据键(与 engine takeover.release 同一清单:
    takeover_release_at / takeover_requested_at / paused_notice_episode),杜绝
    「状态改走了、暂停闸 episode 标记成孤儿」的第二写路径漂移。坐席字段不动:
    assigned_operator_id 是审计痕迹(谁接管的),状态迁移不得顺手抹掉 —— 哨兵
    缺省保留语义由 test_realtime_takeover_edges 钉死。"""
    async with get_session() as session:
        sets = ["status = :status", "updated_at = NOW()"]
        params: dict = {"tid": thread_id, "bid": business_id, "status": status}
        if assigned_operator_id != "__unset__":
            sets.append("assigned_operator_id = :op")
            params["op"] = assigned_operator_id
        sets.append(
            "metadata = CASE WHEN :status <> 'human_takeover' AND status = 'human_takeover' "
            "THEN COALESCE(metadata, '{}'::jsonb) "
            "    - 'takeover_release_at' - 'takeover_requested_at' - 'paused_notice_episode' "
            "ELSE metadata END"
        )
        if tags is not None:
            sets.append("tags = CAST(:tags AS jsonb)")
            params["tags"] = json.dumps(tags)
        row = (
            await session.execute(
                text(
                    f"UPDATE threads SET {', '.join(sets)} WHERE id = :tid AND business_id = :bid "
                    "RETURNING id, status, assigned_operator_id, updated_at"
                ).bindparams(**params)
            )
        ).mappings().first()
        await session.commit()
        if not row:
            return None
        return {
            "threadId": row["id"],
            "status": row["status"],
            "assignedOperatorId": row["assigned_operator_id"],
            "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
        }


async def thread_owner(thread_id: str) -> str | None:
    """线程属主租户(business_id);查无 → None。

    路由层属主闸的廉价访问器(架构审查 #5):此前 store 流订阅裸 SQL 直查、
    live_desk _load_thread_scoped 自抛 404/403、timeline 返 None —— 同一
    「线程归属」三种接口形状。读属主走这里,裁决(403/404 形状)留在各面。
    """
    async with get_session() as session:
        row = (
            await session.execute(
                text("SELECT business_id FROM threads WHERE id = :tid").bindparams(tid=thread_id)
            )
        ).first()
    return str(row[0]) if row and row[0] is not None else None


async def create_thread(thread_id: str, business_id: str, user_id: str | None = None) -> dict | None:
    """显式建线程(web 左栏「开启新一轮对话」/ 商户切换都先建后聊)。

    TS 基线服务端从未实现 POST /api/chat/threads,前端 fetch 404 后静默吞掉,
    「开启新一轮对话」按钮从未真正可用(wayfinder 004 E2E 钉出);此处补齐契约:
    幂等 upsert(ON CONFLICT DO NOTHING),重复点按不报错、不重置既有元数据。

    归属守卫:同 id 线程若属他租户(business_id 不符)或已有属主且与调用者
    user_id 不符,返回 None(路由层转 409)——绝不回显他人线程元数据;
    旧线程无属主时自愈认领给调用者。

    返回值新增 ``created``(new-user-onboarding C):INSERT ... RETURNING 探明
    本次调用是否真插了行 —— 幂等重放(created=False)时路由层据此跳过引导行,
    消息 id 确定性兜底之上双保险。
    """
    async with get_session() as session:
        inserted = await session.execute(
            text(
                'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                "VALUES (:tid, :uid, :bid, 'active', NOW(), NOW()) "
                "ON CONFLICT (id) DO NOTHING RETURNING id"
            ).bindparams(tid=thread_id, uid=user_id, bid=business_id)
        )
        created = inserted.scalar_one_or_none() is not None
        row = (
            await session.execute(
                text(
                    "SELECT id, user_id, business_id, status, created_at, updated_at "
                    "FROM threads WHERE id = :tid AND business_id = :bid"
                ).bindparams(tid=thread_id, bid=business_id)
            )
        ).mappings().first()
        if row is None:
            return None  # 同 id 线程属他租户 → 拒绝回显
        if user_id and row["user_id"] and row["user_id"] != user_id:
            return None  # 同 id 线程已有属主且非调用者 → 拒绝回显
        if user_id and row["user_id"] is None:
            # 旧线程无属主 → 自愈认领(dispatch_chat 自愈建线程的补全路径)
            await session.execute(
                text('UPDATE threads SET "user_id" = :uid, updated_at = NOW() WHERE id = :tid').bindparams(
                    uid=user_id, tid=thread_id
                )
            )
            row = {**row, "user_id": user_id}
        await session.commit()
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "businessId": row["business_id"],
        "status": row["status"] or "active",
        "created": created,
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
        "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def list_user_threads(user_id: str, business_id: str | None = None, limit: int = 20) -> list[dict]:
    """终端顾客会话列表(GET /api/chat/threads,new-user-onboarding B)。

    与 admin 侧 ``list_conversations`` 的差异:属主过滤为严格等值
    ``t.user_id = :uid``,不做 thread-id ILIKE 模糊兜底 —— 顾客端防跨用户
    泄漏;``businessId`` 参数可选收窄(商户切换视图),缺省跨商户全量。
    排序 ``updated_at DESC``(最近活跃在前),上限 50。
    """
    clean_uid = (user_id or "").strip()
    if not clean_uid:
        return []
    lim = max(1, min(50, limit))

    conditions = ['t."user_id" = :uid']
    params: dict = {"uid": clean_uid}
    clean_bid = (business_id or "").lower().strip()
    if clean_bid:
        conditions.append("t.business_id = :bid")
        params["bid"] = clean_bid

    async with get_session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT t.id AS thread_id, t.business_id, t.user_id, t.status, t.created_at, t.updated_at, "
                        "m.content AS last_msg_content, m.role AS last_msg_role, m.timestamp AS last_msg_time "
                        "FROM threads t LEFT JOIN LATERAL ("
                        "  SELECT content, role, timestamp FROM messages WHERE thread_id = t.id "
                        "  ORDER BY created_at DESC, timestamp DESC LIMIT 1"
                        ") m ON true "
                        f"WHERE {' AND '.join(conditions)} ORDER BY t.updated_at DESC LIMIT :lim"
                    ).bindparams(**params, lim=lim)
                )
            )
            .mappings()
            .all()
        )

    items = []
    for r in rows:
        snippet = r["last_msg_content"]
        if snippet and len(snippet) > 80:
            snippet = snippet[:80] + "..."
        # messages.timestamp 是 Text 列(append_message 写 ISO 字符串),旧引擎行亦为 str
        last_time = r["last_msg_time"]
        items.append(
            {
                "id": r["thread_id"],
                "userId": r["user_id"],
                "businessId": r["business_id"],
                "status": r["status"] or "active",
                "createdAt": r["created_at"].isoformat() if r["created_at"] else None,
                "updatedAt": r["updated_at"].isoformat() if r["updated_at"] else None,
                "lastMessageSnippet": snippet,
                "lastMessageRole": r["last_msg_role"],
                "lastMessageTime": last_time if isinstance(last_time, str) else (last_time.isoformat() if last_time else None),
            }
        )
    return items


async def delete_thread(thread_id: str, user_id: str) -> str:
    """删除会话线程(DELETE /api/chat/threads,2026-09-10 补齐 web 侧栏存量缺口)。

    返回 ``deleted`` / ``not_found`` / ``forbidden``(路由层映射 200/404/403)。
    属主守卫:线程已有属主且非调用者,或线程无属主(顾客列表严格等值本就
    看不到无主线程,不开放顾客删除)→ ``forbidden``。

    同一事务删除三表:messages、task_memory(挂起任务态——POST 接受客户端
    自报 threadId,同 id 重建不得复活旧任务态)、threads。审计类记录
    (pending_approvals/intent_logs/session_metrics 等)刻意保留:审批与
    遥测是平台审计资产,不随顾客删线程蒸发。
    """
    clean_tid = (thread_id or "").strip()
    clean_uid = (user_id or "").strip()
    async with get_session() as session:
        row = (
            await session.execute(text("SELECT user_id FROM threads WHERE id = :tid").bindparams(tid=clean_tid))
        ).mappings().first()
        if row is None:
            return "not_found"
        if not clean_uid or not row["user_id"] or row["user_id"] != clean_uid:
            return "forbidden"
        await session.execute(text("DELETE FROM messages WHERE thread_id = :tid").bindparams(tid=clean_tid))
        await session.execute(text("DELETE FROM task_memory WHERE thread_id = :tid").bindparams(tid=clean_tid))
        await session.execute(text("DELETE FROM threads WHERE id = :tid").bindparams(tid=clean_tid))
        await session.commit()
    return "deleted"


def _utc_iso(raw: str | None) -> str:
    """TEXT 列 messages.timestamp 统一写 UTC 带偏移(2026-09-25 收口)。

    此前默认写 naive 本地墙钟,与引擎行(UTC 带偏移)混排成两种格式 —— 字符串
    比较无意义,曾致时间线/记忆窗口「答在问上」(排序锚已改 created_at,本列
    仅剩展示/导出消费,格式统一免得下一处比较重蹈)。调用方传入的 naive 值按
    本地墙钟换算(兼容旧约定),不可解析原样透传,缺省取当前 UTC。
    """
    if not raw:
        return _dt.datetime.now(_dt.UTC).isoformat()
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(_dt.UTC).isoformat()


async def append_message(payload: dict) -> dict:
    """镜像 ConversationRepository.appendMessage(含线程自愈与 operator 角色落库)。"""
    thread_id = payload["threadId"]
    business_id = payload.get("businessId") or "ecommerce"
    async with get_session() as session:
        existing = (
            await session.execute(text("SELECT id FROM threads WHERE id = :tid").bindparams(tid=thread_id))
        ).scalar_one_or_none()
        if not existing:
            await session.execute(
                text(
                    'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                    "VALUES (:tid, :uid, :bid, 'active', NOW(), NOW()) ON CONFLICT (id) DO NOTHING"
                ).bindparams(tid=thread_id, uid=payload.get("userId"), bid=business_id)
            )
        msg_id = payload.get("id") or str(uuid.uuid4())
        timestamp = _utc_iso(payload.get("timestamp"))
        inserted = await session.execute(
            text(
                "INSERT INTO messages (id, thread_id, business_id, role, content, cards, operator_info, image_urls, timestamp) "
                "VALUES (:mid, :tid, :bid, :role, :content, CAST(:cards AS jsonb), CAST(:opinfo AS jsonb), "
                "CAST(:imgurls AS jsonb), :ts) "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(
                mid=msg_id,
                tid=thread_id,
                bid=business_id,
                role=payload["role"],
                content=payload["content"],
                cards=json.dumps(payload["cards"], ensure_ascii=False) if payload.get("cards") else None,
                opinfo=json.dumps(payload.get("operatorInfo"), ensure_ascii=False) if payload.get("operatorInfo") else None,
                imgurls=json.dumps(payload.get("imageUrls"), ensure_ascii=False) if payload.get("imageUrls") else None,
                ts=timestamp,
            )
        )
        # P2 激活 unread_count 存量死列(live-desk-rework §2.3):顾客消息落库单点
        # +1,坐席打开时间线清零(reset_unread),仅坐席台展示。ON CONFLICT 未插入
        # (clientMsgId 幂等重放,P4)不计数。
        if payload.get("role") == "user" and (inserted.rowcount or 0) > 0:
            await session.execute(
                text("UPDATE threads SET unread_count = COALESCE(unread_count, 0) + 1 WHERE id = :tid").bindparams(
                    tid=thread_id
                )
            )
        await session.execute(text("UPDATE threads SET updated_at = NOW() WHERE id = :tid").bindparams(tid=thread_id))
        await session.commit()
    return {
        "id": msg_id,
        "threadId": thread_id,
        "role": payload["role"],
        "content": payload["content"],
        "imageUrls": payload.get("imageUrls"),
        "timestamp": timestamp,
    }


async def publish_thread_message(thread_id: str, payload: dict) -> None:
    """向顾客侧实时频道 thread:{id}:message 发布一帧(store SSE 订阅转发)。

    2026-09-29 实弹修复:坐席 socket 发言与接管/释放系统消息此前只走
    socket 房间广播 + ws:events 频道(无消费方),而商户商城顾客端
    (apps/merchant FloatingChatWidget)没有 socket.io 客户端,唯一实时
    耳朵是本频道 —— 表现为坐席「已接管」连发数条,顾客一条收不到只会回
    「?」。发布失败只打日志不抛:实时增强不回滚已落库真消息,顾客刷新
    走历史接口仍可见。
    """
    try:
        from engine_py.event_bus import get_client

        client = await get_client()
        if client is not None:
            await client.publish(
                THREAD_CHANNEL.format(thread_id=thread_id), json.dumps(payload, ensure_ascii=False)
            )
    except Exception as err:
        print(f"[ConversationRepo] Redis publish thread message failed: {err}")
