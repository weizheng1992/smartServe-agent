"""审批超时解挂行为契约(2026-09-27 夜审 T1 测试补强)。

钉住的缺口:deadline → expired 的转移此前只有集合归属断言,无行为测试 ——
即「waiting 工单过 deadline 后再次评估,必须写库置 expired、提交事务,并按
动作类型返回诚实超时话术」整条链无人看守。契约:

1. waiting + 过期 deadline → state="expired",pending_approvals 收到
   UPDATE status='expired',且 commit 落库(重启后不得复活);
2. 退款(processRefund)与改址(saveUserAddress)话术分流;
3. 未过期的 waiting 工单不走 expired 分支(不写 UPDATE)。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

import engine_py.approvals.gatekeeper as gatekeeper_module
from engine_py.approvals.gatekeeper import ApprovalGatekeeper


class _FakeApproval:
    def __init__(self, deadline: datetime):
        self.id = uuid.uuid4()
        self.thread_id = "thread_expiry"
        self.action_type = "processRefund"
        self.action_payload = {"args": {"orderId": "ORD-1"}}
        self.status = "waiting"
        self.deadline = deadline
        self.created_at = datetime.now() - timedelta(hours=25)


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """只服务 existingApprovalId 直查 + expired UPDATE 路径的最小会话。"""

    def __init__(self, row):
        self._row = row
        self.executed_sql: list[str] = []
        self.commits = 0

    async def execute(self, stmt):
        self.executed_sql.append(str(stmt))
        return _FakeResult(self._row)

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _evaluate_with(fake_session: _FakeSession, tool_name: str) -> dict:
    original = gatekeeper_module.get_session

    def _fake_get_session():
        return fake_session

    gatekeeper_module.get_session = _fake_get_session
    try:
        return asyncio.run(
            ApprovalGatekeeper.evaluate_pending_approval_state(
                {"existingApprovalId": str(fake_session._row.id), "toolName": tool_name}
            )
        )
    finally:
        gatekeeper_module.get_session = original


def test_expired_refund_deadline_marks_expired_and_reports():
    approval = _FakeApproval(datetime.now() - timedelta(minutes=5))
    session = _FakeSession(approval)

    result = _evaluate_with(session, "processRefund")

    assert result["state"] == "expired"
    assert result["approvalId"] == str(approval.id)
    assert "退款暂未执行" in result["message"]
    # 必须真实写库置 expired 并提交(否则重启后 waiting 工单复活)
    assert any("UPDATE pending_approvals SET status = 'expired'" in sql for sql in session.executed_sql)
    assert session.commits >= 1


def test_expired_address_deadline_uses_address_wording():
    approval = _FakeApproval(datetime.now() - timedelta(minutes=5))
    approval.action_type = "saveUserAddress"
    session = _FakeSession(approval)

    result = _evaluate_with(session, "saveUserAddress")

    assert result["state"] == "expired"
    assert "地址修改" in result["message"]
    assert "UPDATE pending_approvals SET status = 'expired'" in " ".join(session.executed_sql)


def test_unexpired_waiting_approval_does_not_hit_expired_branch():
    approval = _FakeApproval(datetime.now() + timedelta(hours=24))
    session = _FakeSession(approval)

    result = _evaluate_with(session, "processRefund")

    # 未过期 → 不写 expired UPDATE(会继续走新建/复用判定,此处只看分支未触发)
    assert result.get("state") != "expired"
    assert all("SET status = 'expired'" not in sql for sql in session.executed_sql)


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])
