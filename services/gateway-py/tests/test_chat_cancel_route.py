"""取消闸契约(S2b,stream-reliability-push 03 号票)。

``chat_turn.cancel_chat_job_gate`` 消费引擎中断原语(interruption):属主核验
→ request_cancel,返回 (响应体, HTTP 状态码)。钉死五类语义:

- 400 身份参数缺失:取消是写动作,严禁落到 dispatch 的缺省身份
  (CUST-8801/ecommerce)上 —— 缺省身份取消 = 任何人可停任何人的作业;
- 404 作业未知/已结束:挂起(审批中)作业 run_agent 早已返回、不在活跃表,
  「审批挂起不可被停止误杀」构造性成立(HITL 边界);
- 403 属主不符:owner = 派发身份(businessId:userId),多租户不变量 #1;
  business 段大小写不敏感(与 store 面 tenant 归一口径同),user 段精确;
- 200 受理:引擎将在下一个图检查点协作停止,终态 interrupted 走 result 帧
  (interrupted:true)照常收口 SSE 流;
- 409 peek 与 cancel 之间刚好结束(窗口竞态,诚实 409 而非谎报已受理)。
"""

from __future__ import annotations

import pytest
from engine_py import interruption

from gateway_py import chat_turn


@pytest.fixture(autouse=True)
def _clean_registry():
    interruption._active_jobs.clear()
    interruption._cancel_requests.clear()
    interruption._job_owners.clear()
    yield
    interruption._active_jobs.clear()
    interruption._cancel_requests.clear()
    interruption._job_owners.clear()


class TestCancelChatJobGate:
    def test_missing_identity_rejected_400(self):
        interruption.register_run("job_1", owner="aurora:CUST-1")
        for kwargs in (
            {"user_id": None, "business_id": None},
            {"user_id": "CUST-1", "business_id": None},
            {"user_id": None, "business_id": "aurora"},
            {"user_id": "", "business_id": "aurora"},
        ):
            payload, status = chat_turn.cancel_chat_job_gate("job_1", **kwargs)
            assert status == 400, f"缺身份必须 400: {kwargs} → {status}"
            assert payload["success"] is False

    def test_unknown_job_404(self):
        payload, status = chat_turn.cancel_chat_job_gate(
            "job_ghost", user_id="CUST-1", business_id="aurora"
        )
        assert status == 404
        assert payload["success"] is False

    def test_suspended_job_404_not_killable(self):
        """审批挂起作业:run_agent 已返回(注销),取消 404 —— HITL 边界在闸层复钉。"""
        interruption.register_run("job_susp", owner="aurora:CUST-1")
        interruption.unregister_run("job_susp")
        _, status = chat_turn.cancel_chat_job_gate(
            "job_susp", user_id="CUST-1", business_id="aurora"
        )
        assert status == 404

    def test_wrong_owner_403(self):
        interruption.register_run("job_2", owner="aurora:CUST-1")
        _, status = chat_turn.cancel_chat_job_gate(
            "job_2", user_id="CUST-2", business_id="aurora"
        )
        assert status == 403
        # 属主不符不得登记取消请求(旁路必须堵死)
        assert interruption.consume_cancel_request("job_2") is False

    def test_business_case_insensitive_user_exact(self):
        interruption.register_run("job_3", owner="aurora:CUST-1")
        _, status = chat_turn.cancel_chat_job_gate(
            "job_3", user_id="CUST-1", business_id="Aurora "
        )
        assert status == 200, "business 段归一大小写与空白(store 面同口径)"
        _, status = chat_turn.cancel_chat_job_gate(
            "job_3", user_id="cust-1", business_id="aurora"
        )
        assert status == 403, "user 段精确匹配"

    def test_accept_200_registers_cancel_request(self):
        interruption.register_run("job_4", owner="aurora:CUST-1")
        payload, status = chat_turn.cancel_chat_job_gate(
            "job_4", user_id="CUST-1", business_id="aurora"
        )
        assert status == 200
        assert payload == {"success": True, "jobId": "job_4", "status": "cancelling"}
        # 引擎侧将消费该请求并在检查点停止
        assert interruption.consume_cancel_request("job_4") is True

    def test_duplicate_cancel_idempotent_while_active(self):
        """重复取消幂等:活跃窗口内两次取消均 200(效果收敛为一次取消请求);
        作业结束后再取消 → 404。"""
        interruption.register_run("job_6", owner="aurora:CUST-1")
        _, first = chat_turn.cancel_chat_job_gate("job_6", user_id="CUST-1", business_id="aurora")
        _, second = chat_turn.cancel_chat_job_gate("job_6", user_id="CUST-1", business_id="aurora")
        assert (first, second) == (200, 200)
        assert interruption.consume_cancel_request("job_6") is True
        assert interruption.consume_cancel_request("job_6") is False
        interruption.unregister_run("job_6")
        _, after_finish = chat_turn.cancel_chat_job_gate(
            "job_6", user_id="CUST-1", business_id="aurora"
        )
        assert after_finish == 404

    def test_409_when_job_finished_between_peek_and_cancel(self, monkeypatch):
        interruption.register_run("job_5", owner="aurora:CUST-1")
        monkeypatch.setattr(chat_turn, "request_cancel", lambda _jid: False)
        payload, status = chat_turn.cancel_chat_job_gate(
            "job_5", user_id="CUST-1", business_id="aurora"
        )
        assert status == 409
        assert payload["success"] is False
