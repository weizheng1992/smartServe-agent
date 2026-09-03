"""周期任务框架 — 第五阶段 v1 落地载体。

单进程 asyncio 调度:固定间隔 + 抖动、逐 tick 容错、启动自检日志。
部署假设:**单实例**(与当前本地/影子期部署一致)。多实例部署前需引入分布式锁
或将周期任务迁移至 Temporal Schedule(见 docs/agent-lifecycle-testing.md 第五阶段落地批次)。

环境开关:``ENGINE_SCHEDULER_ENABLED=0`` 整体关闭(多实例部署时仅保留一个调度实例)。
"""

from __future__ import annotations

import asyncio
import os
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .approvals.outbox_worker import process_pending_events
from .badcase.digest import run_badcase_digest


@dataclass(frozen=True)
class PeriodicTask:
    name: str
    interval_seconds: float
    func: Callable[[], Awaitable[None]]


async def _outbox_reconcile_tick() -> None:
    summary = await process_pending_events()
    if summary.get("processedCount"):
        print(f"[Scheduler:outbox_reconcile] 对账扫描: {summary}")


def default_tasks() -> list[PeriodicTask]:
    return [
        PeriodicTask(name="outbox_reconcile", interval_seconds=30.0, func=_outbox_reconcile_tick),
        PeriodicTask(name="badcase_digest", interval_seconds=6 * 3600.0, func=run_badcase_digest),
    ]


async def _run_task(task: PeriodicTask) -> None:
    await asyncio.sleep(random.uniform(0, task.interval_seconds * 0.1))  # 错峰启动
    print(f"[Scheduler] 周期任务就绪: {task.name}(间隔 {task.interval_seconds:.0f}s)")
    while True:
        try:
            await task.func()
        except Exception as err:  # noqa: BLE001 — 单次失败不影响后续 tick
            print(f"[Scheduler] 任务 {task.name} 执行异常(将继续下一轮): {err}")
        await asyncio.sleep(task.interval_seconds + random.uniform(0, task.interval_seconds * 0.1))


async def start_scheduler() -> None:
    if os.environ.get("ENGINE_SCHEDULER_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        print("[Scheduler] ENGINE_SCHEDULER_ENABLED=0,周期任务未启动")
        return
    tasks = default_tasks()
    print(f"[Scheduler] 启动自检: {len(tasks)} 个周期任务 {[t.name for t in tasks]}(单实例假设)")
    await asyncio.gather(*(_run_task(t) for t in tasks))
