"""审批状态闸 fail-closed 契约(2026-09-25 夜审 HITL 资金安全修复)。

夜审钉死的缺口:gatekeeper 查审批态遇 DB 异常时旧代码返回
{"state": "approved", "isApproved": False} —— 伪装 "approved" 逃过执行引擎
只拦 ("expired","cancelled","rejected") 的拦截面,未知态直落工具调度,
DB 抖动一次即免审执行退款/高额改址(fail-open)。修复后契约:

1. gatekeeper 异常必须回 "error" 态(fail-closed),绝不伪装 "approved";
2. 执行引擎 BLOCKED_APPROVAL_STATES 必须含 "error"(正常批准路径不受影响)。
"""

from __future__ import annotations

import asyncio

import engine_py.approvals.gatekeeper as gatekeeper_module
from engine_py.approvals.gatekeeper import ApprovalGatekeeper
from engine_py.graph.nodes.step_execution_engine import BLOCKED_APPROVAL_STATES


def test_gatekeeper_db_exception_fails_closed_with_error_state():
    """get_session 抛异常 → state 必须是 "error",严禁伪装 "approved"。"""

    def _broken_session():
        raise RuntimeError("db connection lost")

    original = gatekeeper_module.get_session
    gatekeeper_module.get_session = _broken_session
    try:
        result = asyncio.run(
            ApprovalGatekeeper.evaluate_pending_approval_state({"approvalId": "apr_test_fail_closed"})
        )
    finally:
        gatekeeper_module.get_session = original

    assert result["state"] == "error"
    assert result["isApproved"] is False
    assert "审批状态查询失败" in result["error"]


def test_blocked_approval_states_cover_error_and_not_approved():
    """执行引擎拦截面必须含 "error"(gatekeeper 异常态);approved 不在面内。"""
    assert "error" in BLOCKED_APPROVAL_STATES
    assert {"expired", "cancelled", "rejected"} <= BLOCKED_APPROVAL_STATES
    assert "approved" not in BLOCKED_APPROVAL_STATES
