"""Temporal Worker 入口 — 镜像 temporal/worker.py。

影子期监听独立队列 ``agent-tasks-py``(settings.temporal_task_queue),与 TS worker
的 ``agent-tasks`` 物理隔离;切流后改 env 共用同一队列即可。

本入口同时承载周期任务调度(第五阶段 v1):outbox 对账补偿 + badcase 池摘要。
Temporal 不可用时进程退化为纯周期任务进程,对账/摘要仍在线
(ENGINE_SCHEDULER_ENABLED=0 可关闭)。

运行:``python -m engine_py.temporal.worker``(需安装 worker extra:
``uv sync --extra worker``)。
"""

from __future__ import annotations

import asyncio

from ..config import settings


async def main() -> None:
    from ..scheduler import start_scheduler

    scheduler_task = asyncio.create_task(start_scheduler())

    try:
        # temporalio >=1.32:Connection 并入 Client(classmethod connect),Worker 首参即 Client
        from temporalio.client import Client
        from temporalio.worker import Worker

        from .activities import run_agent_state_node
        from .workflows import AgentWorkflow
    except ImportError as err:
        raise SystemExit(
            "[Temporal Worker] temporalio 未安装。执行 `uv sync --extra worker` 后重试。"
        ) from err

    address = settings.temporal_address
    print(f"[Temporal Worker] 正在尝试物理连接至 Temporal Server: {address}")
    try:
        connection = await Client.connect(address)
        worker = Worker(
            connection,
            task_queue=settings.temporal_task_queue,
            workflows=[AgentWorkflow],
            activities=[run_agent_state_node],
        )
        print(f"[Temporal Worker] started, listening on queue: {settings.temporal_task_queue!r}")
        await worker.run()
    except Exception as err:
        print(f"[Temporal Worker Warn] ⚠️ 无法建立 Temporal 连接 ({err})。请检查 Server 是否在线。")

    # Temporal 离线时不再直接退出:保持周期任务(对账/摘要)持续运行
    await scheduler_task


if __name__ == "__main__":
    asyncio.run(main())
