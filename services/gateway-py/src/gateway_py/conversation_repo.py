"""会话仓储 — 镜像 packages/db/src/services/conversationRepository.ts。"""

from __future__ import annotations

import datetime as _dt
import json
import uuid

from sqlalchemy import text

from engine_py.db import get_session


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
                        "m.content AS last_msg_content, m.role AS last_msg_role, m.timestamp AS last_msg_time "
                        "FROM threads t LEFT JOIN LATERAL ("
                        "  SELECT content, role, timestamp FROM messages WHERE thread_id = t.id "
                        "  ORDER BY created_at DESC, timestamp DESC LIMIT 1"
                        ") m ON true "
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
        # 🛡️ 多租户身份校验与自愈补全(镜像 TS 逻辑)
        if clean_biz_id and clean_biz_id != "all":
            if actual_biz_id != clean_biz_id:
                if actual_biz_id == "ecommerce" or clean_biz_id in clean_thread_id.lower():
                    await session.execute(
                        text("UPDATE threads SET business_id = :bid, updated_at = NOW() WHERE id = :tid").bindparams(
                            bid=clean_biz_id, tid=clean_thread_id
                        )
                    )
                    await session.commit()
                    actual_biz_id = clean_biz_id
                else:
                    return None  # 跨租户访问 → 隔离为空

        messages = (
            (
                await session.execute(
                    text(
                        "SELECT id, role, content, cards, timestamp FROM messages WHERE thread_id = :tid "
                        "ORDER BY timestamp ASC, CASE role WHEN 'system' THEN 1 WHEN 'user' THEN 2 "
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
            except Exception:  # noqa: BLE001
                cards = None
        parsed_messages.append(
            {
                "id": str(m["id"]),
                "role": m["role"],
                "content": m["content"],
                "cards": cards,
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
    async with get_session() as session:
        sets = ["status = :status", "updated_at = NOW()"]
        params: dict = {"tid": thread_id, "bid": business_id, "status": status}
        if assigned_operator_id != "__unset__":
            sets.append("assigned_operator_id = :op")
            params["op"] = assigned_operator_id
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
        timestamp = payload.get("timestamp") or _dt.datetime.now().isoformat()
        await session.execute(
            text(
                "INSERT INTO messages (id, thread_id, business_id, role, content, cards, operator_info, timestamp) "
                "VALUES (:mid, :tid, :bid, :role, :content, CAST(:cards AS jsonb), CAST(:opinfo AS jsonb), :ts) "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(
                mid=msg_id,
                tid=thread_id,
                bid=business_id,
                role=payload["role"],
                content=payload["content"],
                cards=json.dumps(payload["cards"], ensure_ascii=False) if payload.get("cards") else None,
                opinfo=json.dumps(payload.get("operatorInfo"), ensure_ascii=False) if payload.get("operatorInfo") else None,
                ts=timestamp,
            )
        )
        await session.execute(text("UPDATE threads SET updated_at = NOW() WHERE id = :tid").bindparams(tid=thread_id))
        await session.commit()
    return {"id": msg_id, "threadId": thread_id, "role": payload["role"], "content": payload["content"], "timestamp": timestamp}
