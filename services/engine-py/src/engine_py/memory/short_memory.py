"""短期记忆 — 镜像 packages/engine/src/memory/shortMemory.ts。

滑动窗口取最近 max_turns*2 条;assistant 内容经租户清洗后返回;
写入使用单调递增时间戳保证同毫秒消息的稳定排序。
"""

from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import case, select, text

from ..db import Message, Thread, get_session
from ..tenant import sanitize_tenant_response

# 与 TS ShortMemory.addMessage 保持一致的固定虚拟用户(线程自愈归属)
_FALLBACK_USER_ID = "83d67d4e-104c-4325-8aa7-10d4389fc725"

_last_global_timestamp_ms = 0


def _monotonic_timestamp(role: str | None) -> str:
    global _last_global_timestamp_ms
    now = int(_dt.datetime.now().timestamp() * 1000)
    role_offset = 10 if role == "assistant" else 0 if role == "system" else 5
    if now <= _last_global_timestamp_ms:
        _last_global_timestamp_ms += role_offset if role_offset > 0 else 1
    else:
        _last_global_timestamp_ms = now + role_offset
    return _dt.datetime.fromtimestamp(_last_global_timestamp_ms / 1000, tz=_dt.UTC).isoformat()


def _infer_business_id(thread_id: str, explicit: str | None = None) -> str:
    """镜像 db.createThread 的智能租户推导:显式值优先,否则按 threadId 关键词推断。"""
    if explicit and explicit != "ecommerce":
        return explicit
    lower = thread_id.lower()
    for key in ("aurora", "nike", "adidas"):
        if key in lower:
            return key
    return explicit or "ecommerce"


class ShortMemory:
    def __init__(self, thread_id: str, max_turns: int = 10, business_id: str | None = None) -> None:
        self.thread_id = thread_id
        self.max_turns = max_turns
        self.business_id = business_id or _infer_business_id(thread_id)

    async def get_messages(self) -> list[dict]:
        try:
            async with get_session() as session:
                rows = (
                    await session.execute(
                        select(Message)
                        .where(Message.thread_id == self.thread_id)
                        .order_by(
                            Message.timestamp,
                            case(
                                (Message.role == "system", 1),
                                (Message.role == "user", 2),
                                (Message.role == "assistant", 3),
                                else_=4,
                            ),
                            Message.id,
                        )
                    )
                ).scalars().all()

                thread_row = (
                    await session.execute(select(Thread).where(Thread.id == self.thread_id).limit(1))
                ).scalar_one_or_none()
                business_id = (thread_row.business_id if thread_row else None) or self.business_id or "ecommerce"

                sliced = list(rows)[-(self.max_turns * 2) :]
                return [
                    {
                        "role": m.role,
                        "content": (
                            sanitize_tenant_response(m.content, business_id)
                            if m.role == "assistant"
                            else m.content
                        ),
                        "cards": m.cards or None,
                    }
                    for m in sliced
                ]
        except Exception as err:
            print(f"[ShortMemory Error] Failed to get messages: {err}")
            return []

    async def add_message(
        self, role: str, content: str, cards: list | None = None
    ) -> None:
        clean_content = "" if content is None else str(content)
        try:
            async with get_session() as session:
                # 线程自愈(镜像 db.createThread:存在则刷新,不存在则建)
                await session.execute(
                    text(
                        'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") '
                        "VALUES (:tid, :uid, :bid, 'active', NOW(), NOW()) "
                        'ON CONFLICT (id) DO UPDATE SET "updated_at" = NOW(), "business_id" = EXCLUDED."business_id"'
                    ).bindparams(tid=self.thread_id, uid=_FALLBACK_USER_ID, bid=self.business_id)
                )
                session.add(
                    Message(
                        id=str(uuid.uuid4()),
                        thread_id=self.thread_id,
                        business_id=self.business_id,
                        role=role,
                        content=clean_content,
                        cards=cards if cards else None,
                        timestamp=_monotonic_timestamp(role),
                    )
                )
                await session.commit()
        except Exception as err:
            print(f"[ShortMemory Error] Failed to add message: {err}")

    async def compress(self, messages: list[dict]) -> str:
        return "Summary of compressed conversation history"
