"""事务发件箱对账 Worker 回归(engine_py/approvals/outbox_worker.py 语义钉死)。

对账四要素(见 .claude/rules/agent-engine.md §1.6):
- 10s 年龄阈值:pending/failed 事件须陈旧过阈值才补发,避开 gatekeeper 同步 Fast-Path 竞争;
- FOR UPDATE SKIP LOCKED:行锁被他者占用时跳过而非阻塞,多实例不重复捞取同一行;
- processing 停滞 >5min 视为进程崩溃遗留,重新入队(retry_count < 5 上限兜底);
- 派发任务自身回写终态:run_agent 成功 → completed(error_message 清空),异常 → failed + 留痕。

基建说明:
- 密封 PG 夹具见 tests/conftest.py 的 pg_factory(session 级共享:容器 + Alembic
  真实 schema + 会话工厂替换;Docker 不可用时整模块 skip);
- ``run_agent`` 是 _dispatch_and_settle 内的延迟导入,经 sys.modules 桩拦截,
  断言确定性 JobId ``job_resume_${approvalId}`` 与 payload 载荷覆写;
- 容器角色级 lock_timeout=3s:若 SKIP LOCKED 语义回归(退化为阻塞等待),
  测试会在 3s 后干净失败而非整场挂死。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import sys
import types
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from engine_py.approvals import outbox_worker
from engine_py.db import ApprovalOutboxEvent

# ---------- 假 run_agent(拦截 _dispatch_and_settle 的延迟导入) ----------


class _FakeRunAgent:
    """记录派发入参;``error`` 非空时模拟 Temporal/执行失败。"""

    def __init__(self) -> None:
        self.calls: list = []
        self.error: Exception | None = None

    async def __call__(self, inp) -> None:
        self.calls.append(inp)
        if self.error is not None:
            raise self.error


@contextmanager
def _stub_run_agent(fake: _FakeRunAgent):
    """把 engine_py.run_agent 替换为桩模块(contextmanager)。

    延迟导入 ``from ..run_agent import AgentJobInput, run_agent`` 会命中
    sys.modules 缓存并 getattr,桩模块持有同名属性即可,无需真实引擎导入链。
    """
    mod = types.ModuleType("engine_py.run_agent")

    class _StubAgentJobInput:
        def __init__(self, *, jobId, threadId, userId, message, businessId):
            self.jobId = jobId
            self.threadId = threadId
            self.userId = userId
            self.message = message
            self.businessId = businessId

    mod.AgentJobInput = _StubAgentJobInput
    mod.run_agent = fake
    held = sys.modules.get("engine_py.run_agent")
    sys.modules["engine_py.run_agent"] = mod
    try:
        yield fake
    finally:
        if held is not None:
            sys.modules["engine_py.run_agent"] = held
        else:
            sys.modules.pop("engine_py.run_agent", None)


# ---------- 表清理 ----------


@pytest.fixture()
def clean_table(pg_factory):
    asyncio.run(_clean(pg_factory))
    return pg_factory


# ---------- 数据与断言助手 ----------


def _mk_event(
    *,
    status: str = "pending",
    age_s: int = 60,
    updated_age_s: int | None = None,
    retry: int = 0,
    payload: dict | None = None,
) -> ApprovalOutboxEvent:
    now = _dt.datetime.now()
    return ApprovalOutboxEvent(
        id=uuid.uuid4(),
        approval_id=str(uuid.uuid4()),
        thread_id="thread_outbox_test",
        event_type="approval_resumed",
        payload=payload or {},
        status=status,
        retry_count=retry,
        error_message="prev round failed" if status == "failed" else None,
        created_at=now - _dt.timedelta(seconds=age_s),
        updated_at=now - _dt.timedelta(seconds=updated_age_s if updated_age_s is not None else age_s),
    )


async def _insert(factory, *events: ApprovalOutboxEvent) -> None:
    async with factory() as session:
        for e in events:
            session.add(e)
        await session.commit()


async def _clean(factory) -> None:
    async with factory() as session:
        await session.execute(text("DELETE FROM approval_outbox_events"))
        await session.commit()


async def _fetch(factory, eid) -> ApprovalOutboxEvent | None:
    async with factory() as session:
        return await session.get(ApprovalOutboxEvent, eid)


async def _drain_background() -> None:
    """等 process_pending_events 里 create_task 出去的派发任务全部回写终态。

    必须与 worker 调用处于同一 asyncio.run 事件循环——loop 关闭后未 await 的
    task 会被直接销毁,终态 UPDATE 永不执行。
    """
    me = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not me]
    if pending:
        await asyncio.gather(*pending)


async def _process_and_drain(older_than_ms: int = 10_000) -> dict:
    summary = await outbox_worker.process_pending_events(older_than_ms=older_than_ms)
    await _drain_background()
    return summary


# ---------- 用例 ----------


def test_年轻pending不补发_避开fast_path竞争(clean_table):
    """10s 年龄阈值:刚落盘的 pending 事件属于同步 Fast-Path 的领地,对账不得抢跑。"""
    factory = clean_table
    ev = _mk_event(age_s=1)
    asyncio.run(_insert(factory, ev))

    summary = asyncio.run(_process_and_drain())  # 默认 older_than_ms=10s

    assert summary == {"processedCount": 0, "dispatchedCount": 0, "failedCount": 0}
    row = asyncio.run(_fetch(factory, ev.id))
    assert row.status == "pending"
    assert row.retry_count == 0


def test_陈旧pending补发_确定性jobid与载荷覆写(clean_table):
    """补发走确定性 JobId ``job_resume_${approvalId}``(物理防重幂等);payload 提供则覆写。"""
    factory = clean_table
    ev_default = _mk_event(payload={})  # jobId 缺省 → job_resume_${approvalId}
    ev_override = _mk_event(
        payload={
            "jobId": "custom_resume_job",
            "userId": "CUST-9",
            "businessId": "aurora",
            "systemPromptText": "System: resume aurora",
        }
    )
    asyncio.run(_insert(factory, ev_default, ev_override))

    fake = _FakeRunAgent()
    with _stub_run_agent(fake):
        summary = asyncio.run(_process_and_drain(older_than_ms=0))

    assert summary["dispatchedCount"] == 2
    jobs = sorted(c.jobId for c in fake.calls)
    assert jobs == sorted([f"job_resume_{ev_default.approval_id}", "custom_resume_job"])

    call_override = next(c for c in fake.calls if c.jobId == "custom_resume_job")
    assert call_override.userId == "CUST-9"
    assert call_override.businessId == "aurora"
    assert call_override.message == "System: resume aurora"

    row = asyncio.run(_fetch(factory, ev_default.id))
    assert row.status == "completed"
    assert row.error_message is None
    assert row.retry_count == 1


def test_派发异常_事件转failed并留痕(clean_table):
    factory = clean_table
    ev = _mk_event(age_s=120)
    asyncio.run(_insert(factory, ev))

    fake = _FakeRunAgent()
    fake.error = RuntimeError("boom: temporal queue unreachable")
    with _stub_run_agent(fake):
        summary = asyncio.run(_process_and_drain(older_than_ms=0))

    assert summary["dispatchedCount"] == 1
    row = asyncio.run(_fetch(factory, ev.id))
    assert row.status == "failed"
    assert "boom: temporal queue unreachable" in (row.error_message or "")
    assert row.retry_count == 1


def test_failed事件进入下一轮对账重试(clean_table):
    """failed 是可重试态:Fast-Path 失败遗留的 pending 语义等价,下一轮照常补发。"""
    factory = clean_table
    ev = _mk_event(status="failed", age_s=120, retry=1)
    asyncio.run(_insert(factory, ev))

    with _stub_run_agent(_FakeRunAgent()):
        summary = asyncio.run(_process_and_drain(older_than_ms=0))

    assert summary["dispatchedCount"] == 1
    row = asyncio.run(_fetch(factory, ev.id))
    assert row.status == "completed"  # 本轮派发成功,错误留痕清空
    assert row.error_message is None
    assert row.retry_count == 2


def test_processing新鲜停滞不捞(clean_table):
    """processing 且 updated_at 在 5 分钟内:视为正在派发,对账不得抢跑双发。"""
    factory = clean_table
    ev = _mk_event(status="processing", age_s=120, updated_age_s=45)
    asyncio.run(_insert(factory, ev))

    summary = asyncio.run(_process_and_drain(older_than_ms=0))

    assert summary["dispatchedCount"] == 0
    row = asyncio.run(_fetch(factory, ev.id))
    assert row.status == "processing"
    assert row.retry_count == 0


def test_processing停滞超5分钟_崩溃遗留重入队(clean_table):
    """processing 停滞 >5min:判定派发进程崩溃遗留,重新入队续跑。"""
    factory = clean_table
    ev = _mk_event(status="processing", age_s=400, updated_age_s=400, retry=2)
    asyncio.run(_insert(factory, ev))

    with _stub_run_agent(_FakeRunAgent()):
        summary = asyncio.run(_process_and_drain(older_than_ms=0))

    assert summary["dispatchedCount"] == 1
    row = asyncio.run(_fetch(factory, ev.id))
    assert row.retry_count == 3  # 2 → 3,入队即计数
    assert row.status == "completed"


def test_retry_count达到上限5_放弃补发(clean_table):
    factory = clean_table
    ev = _mk_event(age_s=600, retry=5)
    asyncio.run(_insert(factory, ev))

    summary = asyncio.run(_process_and_drain(older_than_ms=0))

    assert summary["dispatchedCount"] == 0
    row = asyncio.run(_fetch(factory, ev.id))
    assert row.status == "pending"  # 保持原状,留给人工排查
    assert row.retry_count == 5


def test_行锁被他者占用_SKIP_LOCKED跳过且不阻塞(clean_table):
    """FOR UPDATE SKIP LOCKED 语义:被占行的补发跳过,同行其它事件照常处理。

    若该语义回归为普通 FOR UPDATE,worker 的 SELECT 会被行锁阻塞,
    依赖容器角色的 lock_timeout=3s 让测试以断言失败而非挂死收场。
    """
    factory = clean_table
    ev_locked = _mk_event(age_s=120)
    ev_free = _mk_event(age_s=120)
    asyncio.run(_insert(factory, ev_locked, ev_free))

    async def scenario() -> dict:
        # 另一会话持有 ev_locked 行锁且不提交(模拟并行实例正在处理)
        async with factory() as holder:
            await holder.execute(
                text("SELECT id FROM approval_outbox_events WHERE id = :x FOR UPDATE").bindparams(
                    x=ev_locked.id
                )
            )
            return await _process_and_drain(older_than_ms=0)
        # 会话关闭即回滚,行锁释放

    with _stub_run_agent(_FakeRunAgent()):
        summary = asyncio.run(scenario())

    assert summary["dispatchedCount"] == 1
    row_locked = asyncio.run(_fetch(factory, ev_locked.id))
    row_free = asyncio.run(_fetch(factory, ev_free.id))
    assert row_locked.status == "pending"  # 被锁行未被触碰
    assert row_locked.retry_count == 0
    assert row_free.status == "completed"
