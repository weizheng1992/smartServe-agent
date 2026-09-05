"""任务记忆 — 镜像 packages/engine/src/memory/taskMemory.ts(task_memory 表 upsert)。"""

from __future__ import annotations

import datetime as _dt

from sqlalchemy import select

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
                    row.updated_at = _dt.datetime.now()
                else:
                    session.add(
                        TaskMemoryRow(
                            thread_id=self.thread_id,
                            pending_intents=state,
                            updated_at=_dt.datetime.now(),
                        )
                    )
                await session.commit()
        except Exception as err:
            print(f"[TaskMemory] Failed to save task state to DB: {err}")
