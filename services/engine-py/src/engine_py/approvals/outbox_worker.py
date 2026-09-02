"""事务发件箱对账补偿 Worker — 镜像 approval/approvalOutboxWorker.ts。

周期扫描 pending/failed 发件箱事件,以确定性 JobId(job_resume_${approvalId})
重放调度,根除幽灵审批与双写不一致。
"""

from __future__ import annotations

import asyncio
import datetime as _dt

from sqlalchemy import select, text, update

from ..db import ApprovalOutboxEvent, get_session
from ..memory.short_memory import _FALLBACK_USER_ID


async def process_pending_events(older_than_ms: int = 10_000) -> dict:
    """执行一次对账补偿扫描(默认仅处理 10s 前事件,避免与同步 Fast-Path 竞争)。"""
    summary = {"processedCount": 0, "successCount": 0, "failedCount": 0}
    try:
        async with get_session() as session:
            events = (
                (
                    await session.execute(
                        select(ApprovalOutboxEvent)
                        .where(
                            ApprovalOutboxEvent.status.in_(("pending", "failed")),
                            (ApprovalOutboxEvent.retry_count or 0) < 5,
                        )
                        .order_by(ApprovalOutboxEvent.created_at.desc())
                        .limit(20)
                    )
                )
                .scalars()
                .all()
            )

            cutoff = _dt.datetime.now() - _dt.timedelta(milliseconds=older_than_ms)
            eligible = [
                e
                for e in events
                if older_than_ms == 0 or ((e.created_at or _dt.datetime.now()) <= cutoff)
            ]
            summary["processedCount"] = len(eligible)

            for event in eligible:
                await session.execute(
                    update(ApprovalOutboxEvent)
                    .where(ApprovalOutboxEvent.id == event.id)
                    .values(status="processing", retry_count=(event.retry_count or 0) + 1, updated_at=_dt.datetime.now())
                )
                await session.commit()

                payload = event.payload or {}
                deterministic_job_id = payload.get("jobId") or f"job_resume_{event.approval_id}"
                thread_id = payload.get("threadId") or event.thread_id
                user_id = payload.get("userId") or _FALLBACK_USER_ID
                message = payload.get("systemPromptText") or "System: Resume execution."

                try:
                    from ..run_agent import AgentJobInput, run_agent

                    asyncio.create_task(
                        run_agent(
                            AgentJobInput(jobId=deterministic_job_id, threadId=thread_id, userId=user_id, message=message)
                        )
                    )
                    await session.execute(
                        update(ApprovalOutboxEvent)
                        .where(ApprovalOutboxEvent.id == event.id)
                        .values(status="completed", error_message=None, updated_at=_dt.datetime.now())
                    )
                    await session.commit()
                    summary["successCount"] += 1
                except Exception as dispatch_err:  # noqa: BLE001
                    await session.execute(
                        update(ApprovalOutboxEvent)
                        .where(ApprovalOutboxEvent.id == event.id)
                        .values(status="failed", error_message=str(dispatch_err), updated_at=_dt.datetime.now())
                    )
                    await session.commit()
                    summary["failedCount"] += 1
    except Exception as err:  # noqa: BLE001
        print(f"[ApprovalOutboxWorker] 扫描发件箱异常: {err}")
    return summary


_task: asyncio.Task | None = None


def start_polling(interval_ms: int = 5000) -> None:
    """启动后台轮询补偿(单实例单任务)。"""
    global _task
    if _task is not None:
        return

    async def _loop() -> None:
        while True:
            try:
                await process_pending_events(10_000)
            except Exception as err:  # noqa: BLE001
                print(f"[ApprovalOutboxWorker] 轮询异常: {err}")
            await asyncio.sleep(interval_ms / 1000)

    _task = asyncio.get_event_loop().create_task(_loop()) if asyncio.get_event_loop().is_running() else None


def stop_polling() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
