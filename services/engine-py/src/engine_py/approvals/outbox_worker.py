"""事务发件箱对账补偿 Worker — Fast-Path 失败事件的兜底重放(镜像 approval/approvalOutboxWorker.ts)。

周期调度由 ``engine_py.scheduler`` 承担。原 ``start_polling`` 实现存在两个缺陷,已随重构移除:
1. 事件循环未运行时静默返回 None(看似启动实则未启动);
2. ``create_task`` 发射后立刻标 completed 的"假完成"。

现实现要点:
- ``FOR UPDATE SKIP LOCKED`` 防多实例重复捞取同一批事件;
- 派发任务自身回写终态(run_agent 真正跑完才标 completed,异常标 failed);
- 10s 年龄阈值避免与 gatekeeper 同步 Fast-Path 竞争;
- ``processing`` 停滞超 5 分钟视为进程崩溃遗留,重新入队(上限 retry_count < 5)。
"""

from __future__ import annotations

import asyncio
import datetime as _dt

from sqlalchemy import and_, func, or_, select, text, update

from ..db import ApprovalOutboxEvent, get_session
from ..memory.short_memory import _FALLBACK_USER_ID


async def process_pending_events(older_than_ms: int = 10_000) -> dict:
    """执行一次对账补偿扫描(默认仅处理 10s 前事件,避免与同步 Fast-Path 竞争)。"""
    summary = {"processedCount": 0, "dispatchedCount": 0, "failedCount": 0}
    try:
        now = _dt.datetime.now()
        age_cutoff = now - _dt.timedelta(milliseconds=older_than_ms)
        stale_cutoff = now - _dt.timedelta(minutes=5)

        async with get_session() as session:
            events = (
                (
                    await session.execute(
                        select(ApprovalOutboxEvent)
                        .where(
                            or_(
                                ApprovalOutboxEvent.status.in_(("pending", "failed")),
                                and_(
                                    ApprovalOutboxEvent.status == "processing",
                                    func.coalesce(ApprovalOutboxEvent.updated_at, ApprovalOutboxEvent.created_at)
                                    <= stale_cutoff,
                                ),
                            ),
                            (ApprovalOutboxEvent.retry_count or 0) < 5,
                        )
                        .order_by(ApprovalOutboxEvent.created_at.desc())
                        .limit(20)
                        .with_for_update(skip_locked=True)
                    )
                )
                .scalars()
                .all()
            )

            eligible = []
            for e in events:
                if e.status == "processing" or (e.created_at or now) <= age_cutoff:
                    eligible.append(e)

            for event in eligible:
                await session.execute(
                    update(ApprovalOutboxEvent)
                    .where(ApprovalOutboxEvent.id == event.id)
                    .values(
                        status="processing",
                        retry_count=(event.retry_count or 0) + 1,
                        updated_at=now,
                    )
                )
                await session.commit()  # 释放行锁,派发转后台
                summary["processedCount"] += 1

                payload = event.payload or {}
                job_id = payload.get("jobId") or f"job_resume_{event.approval_id}"
                thread_id = payload.get("threadId") or event.thread_id
                user_id = payload.get("userId") or _FALLBACK_USER_ID
                business_id = payload.get("businessId") or "ecommerce"
                message = payload.get("systemPromptText") or "System: Resume execution."

                asyncio.create_task(
                    _dispatch_and_settle(str(event.id), job_id, thread_id, user_id, message, business_id)
                )
                summary["dispatchedCount"] += 1
    except Exception as err:  # noqa: BLE001
        print(f"[ApprovalOutboxWorker] 扫描发件箱异常: {err}")
    return summary


async def _dispatch_and_settle(
    event_id: str, job_id: str, thread_id: str, user_id: str, message: str, business_id: str = "ecommerce"
) -> None:
    """派发恢复任务并由任务自身回写终态——确定性 JobId ``job_resume_${approvalId}`` 物理防重幂等。"""
    try:
        from ..run_agent import AgentJobInput, run_agent

        await run_agent(
            AgentJobInput(
                jobId=job_id, threadId=thread_id, userId=user_id, message=message, businessId=business_id
            )
        )
        async with get_session() as session:
            await session.execute(
                text(
                    "UPDATE approval_outbox_events SET status = 'completed', error_message = NULL, "
                    "updated_at = NOW() WHERE id = CAST(:eid AS uuid)"
                ).bindparams(eid=event_id)
            )
            await session.commit()
    except Exception as err:  # noqa: BLE001
        async with get_session() as session:
            await session.execute(
                text(
                    "UPDATE approval_outbox_events SET status = 'failed', error_message = :err, "
                    "updated_at = NOW() WHERE id = CAST(:eid AS uuid)"
                ).bindparams(err=str(err)[:500], eid=event_id)
            )
            await session.commit()
        print(f"[ApprovalOutboxWorker] 派发失败 event={event_id} job={job_id}: {err}")
