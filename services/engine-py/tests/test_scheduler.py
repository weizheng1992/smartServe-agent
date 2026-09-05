"""周期任务调度器回归(engine_py/scheduler.py)。

钉死三件事:
- ``ENGINE_SCHEDULER_ENABLED`` 开关(0/false/no,忽略大小写与空白)整体关闭,
  连 default_tasks 都不该被触碰;
- 默认任务清单:outbox 对账(30s)+ 坏例池摘要(6h);
- 单 tick 异常不终止循环(逐 tick 容错),任务按间隔反复执行。

纯 asyncio 逻辑,不依赖 DB;间隔用毫秒级小值 + 抖动按比例缩小,无需冻结随机源。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest

from engine_py import scheduler
from engine_py.scheduler import PeriodicTask, _run_task, default_tasks, start_scheduler


@pytest.mark.parametrize("flag", ["0", "false", "no", " 0 ", "FALSE"])
def test_开关关闭_周期任务整体不启动(monkeypatch, flag):
    def _must_not_call():
        raise AssertionError("开关关闭时不应触碰默认任务清单")

    monkeypatch.setenv("ENGINE_SCHEDULER_ENABLED", flag)
    monkeypatch.setattr(scheduler, "default_tasks", _must_not_call)

    # 关闭时应立即返回(而非进入 gather 常驻);超时 1s 兜底防挂死
    asyncio.run(asyncio.wait_for(start_scheduler(), timeout=1.0))


def test_默认任务清单_对账30s坏例摘要6h():
    tasks = {t.name: t for t in default_tasks()}
    assert set(tasks) == {"outbox_reconcile", "badcase_digest"}
    assert tasks["outbox_reconcile"].interval_seconds == 30.0
    assert tasks["badcase_digest"].interval_seconds == 6 * 3600.0


def _run_until(coro_factory, predicate, budget_s: float = 2.0) -> None:
    """在事件循环里跑 coro_factory 产出的任务,直到 predicate 为真或预算耗尽后取消。"""

    async def _wrapper() -> None:
        task = asyncio.create_task(coro_factory())
        deadline = asyncio.get_running_loop().time() + budget_s
        while not predicate() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.005)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    asyncio.run(_wrapper())


def test_开关开启_任务按间隔反复执行(monkeypatch):
    calls: list[int] = []

    async def probe() -> None:
        calls.append(1)

    monkeypatch.delenv("ENGINE_SCHEDULER_ENABLED", raising=False)
    monkeypatch.setattr(
        scheduler, "default_tasks", lambda: [PeriodicTask(name="probe", interval_seconds=0.02, func=probe)]
    )

    _run_until(start_scheduler, lambda: len(calls) >= 3)

    assert len(calls) >= 3, f"周期任务未按间隔反复执行(仅 {len(calls)} 次)"


def test_单tick异常不终止循环():
    calls: list[int] = []

    async def flaky() -> None:
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("tick failed")

    task = PeriodicTask(name="flaky", interval_seconds=0.02, func=flaky)
    _run_until(lambda: _run_task(task), lambda: len(calls) >= 3)

    assert len(calls) >= 3, "tick 异常导致循环提前终止"
