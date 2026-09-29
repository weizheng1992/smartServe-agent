"""转人工排队接线契约(2026-09-29 实弹)。

实弹事故第三根源:顾客「转人工」走 planner 快轨建 human_escalation HITL 工单,
但 create_pending_approval_ticket 只写 pending_approvals(审计),从不落接管
活态 —— P1 排队机制(threads.status=human_takeover+坐席空=呼叫中;坐席台
呼叫中置顶;排队超时回落 AI)整套建成却零生产调用方,顾客拿到的罐头文案
承诺「加密推送到主管队列 / 1 分钟内接管」而系统里没有任何队列。接线契约:

1. human_escalation 工单 → 接管活态翻「呼叫中」(status 翻 + 坐席空 +
   takeover_requested_at 落 metadata),AI 暂停闸立即生效(paused_reply 排队文案);
2. 非 human_escalation 工单(退款等高危动作)不动接管态;
3. 工单退化审计语义不变(waiting 照旧,重复呼叫不重复建票);
4. 坐席认领 → paused_reply 切「已接待」文案;排队超时回落 → 回 None(AI 复答)。
"""

from __future__ import annotations

import asyncio

from engine_py.approvals import takeover
from engine_py.approvals.gatekeeper import ApprovalPolicyEngine

_QUEUED_MARK = "呼叫"
_CLAIMED_MARK = "已由人工客服接待"


def _run(coro):
    return asyncio.run(coro)


async def _mk_thread(tid: str) -> None:
    from sqlalchemy import text

    from engine_py.db import get_session

    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO threads (id, user_id, business_id, status) "
                "VALUES (:t, 'u_esc_wire', 'aurora', 'active') ON CONFLICT (id) DO NOTHING"
            ).bindparams(t=tid)
        )
        await session.commit()


async def _create_ticket(tid: str, action_type: str) -> dict:
    return await ApprovalPolicyEngine.create_pending_approval_ticket(
        {
            "threadId": tid,
            "userId": "u_esc_wire",
            "actionType": action_type,
            "actionPayload": {"reason": "User requested human customer support intervention", "triggerSource": "user_request"},
            "jobId": "",
            "stepToRun": {"id": "step_fast_human_escalation", "description": "转人工", "status": "pending"},
            "currentPlan": {"subtasks": [{"id": "step_fast_human_escalation", "status": "pending"}]},
            "currentIndex": 0,
        }
    )


async def _waiting_count(tid: str) -> int:
    from sqlalchemy import text

    from engine_py.db import get_session

    async with get_session() as session:
        rows = (
            await session.execute(
                text("SELECT id FROM pending_approvals WHERE thread_id = :t AND status = 'waiting'").bindparams(t=tid)
            )
        ).scalars().all()
    return len(rows)


async def _requested_at(tid: str):
    from sqlalchemy import text

    from engine_py.db import get_session

    async with get_session() as session:
        return (
            await session.execute(
                text("SELECT metadata->>'takeover_requested_at' FROM threads WHERE id = :t").bindparams(t=tid)
            )
        ).scalar()


def test_escalation_ticket_enters_queue(pg_factory):
    async def _body():
        tid = f"esc_wire_{uuid_hex()}"
        await _mk_thread(tid)

        await _create_ticket(tid, "human_escalation")

        state = await takeover.thread_state(tid)
        assert state["status"] == "human_takeover", "转人工工单必须把接管活态翻呼叫中"
        assert state["assignedOperatorId"] is None, "呼叫中 = 坐席空(认领由坐席通道落列)"
        assert await _requested_at(tid), "排队时长起点必须落 metadata.takeover_requested_at"
        assert await _waiting_count(tid) == 1, "工单退化审计:waiting 工单照旧"
        reply = await takeover.paused_reply(tid)
        assert reply and _QUEUED_MARK in reply, "排队中暂停文案必须如实说「呼叫中」"

    _run(_body())


def test_non_escalation_ticket_leaves_state(pg_factory):
    async def _body():
        tid = f"esc_no_wire_{uuid_hex()}"
        await _mk_thread(tid)

        await _create_ticket(tid, "process_refund")

        state = await takeover.thread_state(tid)
        assert state["status"] == "active", "退款等高危工单不翻接管态(暂停闸走工单路径,不占排队)"
        assert await takeover.paused_reply(tid) is None

    _run(_body())


def test_repeat_call_keeps_first_requested_at(pg_factory):
    async def _body():
        tid = f"esc_repeat_{uuid_hex()}"
        await _mk_thread(tid)

        await _create_ticket(tid, "human_escalation")
        first = await _requested_at(tid)
        await _create_ticket(tid, "human_escalation")

        assert await _waiting_count(tid) == 1, "重复呼叫不重复建票(既有 waiting 去重)"
        assert await _requested_at(tid) == first, "同一接管期排队起点取首次呼叫时刻"

    _run(_body())


def test_claim_switches_reply_and_queue_fallback_releases(pg_factory):
    async def _body():
        tid = f"esc_fallback_{uuid_hex()}"
        await _mk_thread(tid)
        await _create_ticket(tid, "human_escalation")

        assert await takeover.assign_operator(tid, "op@aurora") is True
        reply = await takeover.paused_reply(tid)
        assert reply and _CLAIMED_MARK in reply, "认领后暂停文案切「已接待」"

        # 排队超时回落扫描只对坐席空的行生效;认领中的走掉线释放路径 ——
        # 释放后暂停闸解除,paused_reply 回 None(AI 复答)
        await takeover.release_takeover(tid)
        assert await takeover.paused_reply(tid) is None
        assert (await takeover.thread_state(tid))["status"] == "active"

    _run(_body())


def test_gate_notice_only_first_round_then_silent(pg_factory):
    """防复读契约(paused_gate,2026-09-29 实弹第二幕):顾客每条消息都收
    「已由人工客服接待」罐头,接管期刷屏。提示槽每接管期只认领一次:首轮
    给分形文案,其后静默;认领切换不重置期(坐席真人回复才是信号);释放
    清标记,新接管期(含 socket 链无 requested_at 的空期)再给。"""
    async def _body():
        tid = f"gate_dedup_{uuid_hex()}"
        await _mk_thread(tid)

        await _create_ticket(tid, "human_escalation")

        paused, notice = await takeover.paused_gate(tid)
        assert paused and notice and _QUEUED_MARK in notice
        # 其后轮次静默,闸不撤
        assert await takeover.paused_gate(tid) == (True, None)
        assert await takeover.paused_gate(tid) == (True, None)

        # 认领不重置接管期:坐席已接入,罐头依旧不再出(真人回复即信号)
        assert await takeover.assign_operator(tid, "op@aurora") is True
        assert await takeover.paused_gate(tid) == (True, None)

        # 释放清标记 → 新接管期首轮再给(HTTP 链:mark_takeover_requested 新期)
        assert await takeover.release_takeover(tid) is True
        assert await takeover.paused_gate(tid) == (False, None)
        await takeover.mark_takeover_requested(tid)
        paused2, notice2 = await takeover.paused_gate(tid)
        assert paused2 and notice2 and _QUEUED_MARK in notice2
        assert await takeover.paused_gate(tid) == (True, None)

        # socket 链起手(update_conversation_status 直翻状态,不写 requested_at)
        # 以空串为期:同样首轮给、其后静默 —— 实弹 live 库 e2e_* 残留即此形态
        assert await takeover.release_takeover(tid) is True
        from sqlalchemy import text as _text

        from engine_py.db import get_session as _gs

        async with _gs() as session:
            await session.execute(
                _text("UPDATE threads SET status = 'human_takeover' WHERE id = :t").bindparams(t=tid)
            )
            await session.commit()
        paused3, notice3 = await takeover.paused_gate(tid)
        assert paused3 and notice3
        assert await takeover.paused_gate(tid) == (True, None)

    _run(_body())


def test_queue_fallback_releases_unclaimed_wait(pg_factory):
    async def _body():
        tid = f"esc_expire_{uuid_hex()}"
        await _mk_thread(tid)
        await _create_ticket(tid, "human_escalation")

        from sqlalchemy import text

        from engine_py.db import get_session

        async with get_session() as session:
            await session.execute(
                text(
                    "UPDATE threads SET metadata = jsonb_set(metadata, '{takeover_requested_at}', "
                    "to_jsonb(NOW() - interval '1 hour')) WHERE id = :t"
                ).bindparams(t=tid)
            )
            await session.commit()

        released = await takeover.release_expired_queue_waits(600)
        assert tid in released, "超时无人认领必须回落 AI"
        assert await takeover.paused_reply(tid) is None

    _run(_body())


def uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex[:8]
