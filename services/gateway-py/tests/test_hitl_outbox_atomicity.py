"""事务发件箱原子性钉死(架构不变量 #3;2026-09-26 夜审 ④ 测试补强)。

审批裁决的工单状态变更与 approval_outbox_events 事件必须在同一事务原子
提交 —— 注入「事件写入失败」后,裁决必须整体回滚:工单不得单侧翻转为
approved/rejected 而事件蒸发(事件蒸发 = 恢复派发永不发生,顾客侧永久
挂起等待一个不会到来的续跑)。
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded", "staff_auth")


async def _insert_waiting_ticket(approval_id: str) -> str:
    from engine_py.db import get_session

    # A4 收口后商户面按员工真租户做对象级校验:工单须落在员工租户(aurora)名下
    tid = f"hitl_atomic_thread_{_TS}"
    await create_thread(tid, "u_hitl_atomic", "aurora")
    async with get_session() as session:
        await session.execute(
            sa.text(
                "INSERT INTO pending_approvals (id, thread_id, business_id, status, action_type, reason, "
                "action_payload, deadline) VALUES (CAST(:id AS uuid), :tid, 'aurora', 'waiting', 'processRefund', "
                "'发件箱原子性工单', CAST('{}' AS jsonb), NOW() + INTERVAL '24 hours') "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(id=approval_id, tid=tid)
        )
        await session.commit()
    return tid


async def _ticket_status(approval_id: str) -> str | None:
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                sa.text("SELECT status FROM pending_approvals WHERE id = CAST(:aid AS uuid)").bindparams(aid=approval_id)
            )
        ).first()
    return row[0] if row else None


async def _outbox_count(approval_id: str) -> int:
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                sa.text("SELECT COUNT(*) FROM approval_outbox_events WHERE approval_id = :aid").bindparams(
                    aid=approval_id
                )
            )
        ).first()
    return int(row[0]) if row else 0


class TestOutboxAtomicity:
    async def test_event_write_failure_rolls_back_status_change(self, client, staff_auth, monkeypatch):
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)

        from engine_py.approvals import gatekeeper

        class _OutboxDown:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("outbox unavailable")

        monkeypatch.setattr(gatekeeper, "ApprovalOutboxEvent", _OutboxDown)

        res = await client.post(
            "/api/admin/approvals",
            json={"approvalId": aid, "action": "approve", "actor": "merchant_operator"},
            headers=staff_auth,
        )
        assert res.status_code == 500, res.text
        assert res.json().get("success") is not True

        assert await _ticket_status(aid) == "waiting", "事件写入失败时工单状态必须回滚为 waiting"
        assert await _outbox_count(aid) == 0

    async def test_happy_path_writes_status_and_event_together(self, client, staff_auth):
        """对照组:正常裁决两写同现(与 test_approval_lifecycle_gateway 呼应)。"""
        aid = str(uuid.uuid4())
        await _insert_waiting_ticket(aid)

        res = await client.post(
            "/api/admin/approvals",
            json={"approvalId": aid, "action": "approve", "actor": "merchant_operator"},
            headers=staff_auth,
        )
        assert res.status_code == 200, res.text

        assert await _ticket_status(aid) == "approved"
        assert await _outbox_count(aid) == 1


async def _insert_pending_event(approval_id: str, *, age_seconds: int = 30, status: str = "pending") -> str:
    """直插一条 Fast-Path 派发失败遗留的对账候选(默认 30s 龄,越过 10s 竞争阈值)。"""
    import json as _json

    from engine_py.db import get_session

    event_id = str(uuid.uuid4())
    payload = _json.dumps(
        {
            "jobId": f"job_resume_{approval_id}",
            "threadId": f"outbox_thread_{_TS}",
            "userId": "u_hitl_atomic",
            "businessId": "aurora",
            "systemPromptText": "System: Human approval granted. Please execute the requested action.",
            "nextStatus": "approved",
        }
    )
    async with get_session() as session:
        await session.execute(
            sa.text(
                "INSERT INTO approval_outbox_events (id, approval_id, thread_id, event_type, payload, "
                "status, retry_count, created_at, updated_at) VALUES (CAST(:eid AS uuid), :aid, :tid, "
                "'resume_execution', CAST(:payload AS jsonb), :status, 0, "
                "NOW() - CAST(:age || ' seconds' AS interval), NOW())"
            ).bindparams(eid=event_id, aid=approval_id, tid=f"outbox_thread_{_TS}", payload=payload, status=status, age=age_seconds)
        )
        await session.commit()
    return event_id


async def _event_state(event_id: str) -> tuple[str | None, str | None, int | None]:
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                sa.text(
                    "SELECT status, error_message, retry_count FROM approval_outbox_events "
                    "WHERE id = CAST(:eid AS uuid)"
                ).bindparams(eid=event_id)
            )
        ).first()
    return (row[0], row[1], row[2]) if row else (None, None, None)


async def _wait_event_settled(event_id: str, want: str, timeout_s: float = 3.0) -> tuple[str | None, str | None, int | None]:
    """_dispatch_and_settle 经 create_task 发射,轮询到终态(超时即失败不静默)。"""
    import asyncio

    deadline = asyncio.get_event_loop().time() + timeout_s
    state = await _event_state(event_id)
    while state[0] != want and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)
        state = await _event_state(event_id)
    return state


class TestOutboxWorkerCompensation:
    """缺口2(2026-09-28 夜审):Fast-Path 派发失败 → 事件留 pending →
    outbox worker 对账补偿缝合。此前 process_pending_events 零覆盖 ——
    而 HITL 不变量 #3 的最终兜底正是这条补偿链。"""

    async def test_pending_event_dispatched_and_completed(self, monkeypatch):
        # ⚠️ 不可 `import engine_py.run_agent as m` —— 包 __init__ 的
        # `from .run_agent import run_agent` 会把包属性遮蔽成函数,as 子句
        # 取到的是函数而非模块;经 sys.modules 取真模块再打补丁
        # (_dispatch_and_settle 是函数内延迟 import,补丁生效)。
        import sys

        run_agent_mod = sys.modules["engine_py.run_agent"]
        from engine_py.approvals.outbox_worker import process_pending_events

        seen: list = []

        async def _fake_run_agent(job_input):
            seen.append(job_input)

        monkeypatch.setattr(run_agent_mod, "run_agent", _fake_run_agent)

        aid = str(uuid.uuid4())
        event_id = await _insert_pending_event(aid)

        summary = await process_pending_events(older_than_ms=10_000)
        assert summary["dispatchedCount"] >= 1
        # 断言只锚本例事件(同容器他文件遗留的陈旧候选可能同批被扫,不属于本契约)
        ours = [j for j in seen if j.job_id == f"job_resume_{aid}"]
        assert len(ours) == 1, "候选事件必须恰好派发一次(确定性 JobId 幂等由 run_agent 侧承担)"
        assert ours[0].business_id == "aurora"

        status, error, retries = await _wait_event_settled(event_id, "completed")
        assert status == "completed", f"派发成功后必须由任务自身回写终态,实得 {status}/{error}"
        assert error is None
        assert retries == 1, "扫描即置 processing 并 +1 retry_count"

    async def test_run_agent_failure_marks_failed_with_error_message(self, monkeypatch):
        # ⚠️ 不可 `import engine_py.run_agent as m` —— 包 __init__ 的
        # `from .run_agent import run_agent` 会把包属性遮蔽成函数,as 子句
        # 取到的是函数而非模块;经 sys.modules 取真模块再打补丁
        # (_dispatch_and_settle 是函数内延迟 import,补丁生效)。
        import sys

        run_agent_mod = sys.modules["engine_py.run_agent"]
        from engine_py.approvals.outbox_worker import process_pending_events

        async def _boom(_job_input):
            raise RuntimeError("恢复派发模拟失败")

        monkeypatch.setattr(run_agent_mod, "run_agent", _boom)

        aid = str(uuid.uuid4())
        event_id = await _insert_pending_event(aid)

        await process_pending_events(older_than_ms=10_000)
        status, error, _ = await _wait_event_settled(event_id, "failed")
        assert status == "failed", "run_agent 抛错必须落 failed 而非蒸发"
        assert error and "恢复派发模拟失败" in error, "error_message 必须可观测(诊断入口,记忆坑位)"

    async def test_fresh_event_below_age_threshold_not_processed(self, monkeypatch):
        """10s 年龄阈值防与同步 Fast-Path 竞争:新鲜事件不得被扫描卷走。"""
        # ⚠️ 不可 `import engine_py.run_agent as m` —— 包 __init__ 的
        # `from .run_agent import run_agent` 会把包属性遮蔽成函数,as 子句
        # 取到的是函数而非模块;经 sys.modules 取真模块再打补丁
        # (_dispatch_and_settle 是函数内延迟 import,补丁生效)。
        import sys

        run_agent_mod = sys.modules["engine_py.run_agent"]
        from engine_py.approvals.outbox_worker import process_pending_events

        seen: list = []

        async def _fake_run_agent(job_input):
            seen.append(job_input)

        monkeypatch.setattr(run_agent_mod, "run_agent", _fake_run_agent)

        aid = str(uuid.uuid4())
        event_id = await _insert_pending_event(aid, age_seconds=0)

        await process_pending_events(older_than_ms=10_000)
        assert all(j.job_id != f"job_resume_{aid}" for j in seen), "年龄阈值内的事件留给 Fast-Path,补偿链不得抢跑"
        status, _, retries = await _event_state(event_id)
        assert status == "pending" and retries == 0
