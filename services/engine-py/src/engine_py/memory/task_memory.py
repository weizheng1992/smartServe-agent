"""任务记忆 — 镜像 packages/engine/src/memory/taskMemory.ts(task_memory 表 upsert)。"""

from __future__ import annotations

from sqlalchemy import func, select

from ..db import TaskMemoryRow, get_session


class TaskMemory:
    def __init__(self, thread_id: str) -> None:
        self.thread_id = thread_id

    async def get_task_state(self) -> dict | None:
        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        select(TaskMemoryRow).where(TaskMemoryRow.thread_id == self.thread_id).limit(1)
                    )
                ).scalar_one_or_none()
                return row.pending_intents if row else None
        except Exception as err:
            print(f"[TaskMemory] Failed to get task state from DB: {err}")
            return None

    async def save_task_state(self, state: dict) -> None:
        try:
            async with get_session() as session:
                row = (
                    await session.execute(
                        select(TaskMemoryRow).where(TaskMemoryRow.thread_id == self.thread_id).limit(1)
                    )
                ).scalar_one_or_none()
                if row:
                    row.pending_intents = state
                    # updated_at 落 DB 钟(server_default now() 同源 UTC):
                    # 本地 naive now 在非 UTC 部署下覆写成未来 8h 的混源时间戳
                    # (2026-09-29 夜审 F15 波及复核)
                    row.updated_at = func.now()
                else:
                    session.add(
                        TaskMemoryRow(
                            thread_id=self.thread_id,
                            pending_intents=state,
                            # 新建走列默认(server_default now()),不手填本地钟
                        )
                    )
                await session.commit()
        except Exception as err:
            print(f"[TaskMemory] Failed to save task state to DB: {err}")
