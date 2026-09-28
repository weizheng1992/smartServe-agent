"""P1 真源归一 + 事故止血契约(live-desk-rework spec §3 P1 行)。

threads.status + assigned_operator_id 是接管活态唯一真源(复合语义:
``human_takeover`` 且坐席空 = 呼叫中/排队;非空 = 接管中),工单退化为审计。

① 双写一致性:顾客呼叫 → human_takeover + 坐席空;员工认领 → 落坐席;
   坐席发言落 ``role='operator'`` + operator_info(前缀拼接退役);
   释放 → active,系统提示恰落一条。
② AI 暂停闸:接管期 dispatch/store_chat 用户行照常落库但**不建作业**
   (jobId=""+isHumanActive),release 后下一条自然恢复建作业。
③ 掉线超时释放:权威 = DB deadline + ``release_expired_takeovers`` 幂等
   扫描(过期释放、重复扫描 0 行、未来 deadline 不动、排队态不动);
   掉线写 deadline 仅首次生效,重连信号取消。
④ release_takeover 语义:缺 threadId 400、重复释放幂等不重复落系统消息、
   跨租户 403(双路由通道)、未知线程 fail-open 诚实无副作用。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded")

STAFF_EMAIL = "test@example.com"  # staff_auth fixture 直签的 aurora 员工


async def _mk_thread(prefix: str, business_id: str = "aurora", user_id: str | None = None) -> tuple[str, str]:
    tid = f"{prefix}_{_TS}_{uuid.uuid4().hex[:6]}"
    uid = user_id or f"u_{prefix}_{uuid.uuid4().hex[:6]}"
    await create_thread(tid, uid, business_id)
    return tid, uid


async def _thread_row(thread_id: str) -> dict:
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, assigned_operator_id, "
                    "jsonb_exists(COALESCE(metadata, '{}'::jsonb), 'takeover_requested_at') AS requested, "
                    "metadata->>'takeover_release_at' AS deadline "
                    "FROM threads WHERE id = :tid"
                ).bindparams(tid=thread_id)
            )
        ).mappings().first()
    assert row is not None, f"线程 {thread_id} 不存在"
    return dict(row)


async def _msgs(thread_id: str) -> list[dict]:
    from engine_py.db import get_session

    async with get_session() as session:
        rows = (
            await session.execute(
                text("SELECT role, content, operator_info FROM messages WHERE thread_id = :tid").bindparams(
                    tid=thread_id
                )
            )
        ).mappings().all()
    return [dict(r) for r in rows]


async def _count_msgs(thread_id: str, needle: str) -> int:
    from engine_py.db import get_session

    async with get_session() as session:
        return (
            await session.execute(
                text("SELECT COUNT(*) FROM messages WHERE thread_id = :tid AND content LIKE :kw").bindparams(
                    tid=thread_id, kw=f"%{needle}%"
                )
            )
        ).scalar()


async def _force_takeover(thread_id: str, operator: str | None, deadline: str | None = None) -> None:
    """直写真源到指定形态(超时扫描组的排布用;HTTP 链归 HTTP 用例钉)。"""
    from engine_py.approvals import takeover

    await takeover.mark_takeover_requested(thread_id)
    if operator:
        await takeover.assign_operator(thread_id, operator)
    if deadline:
        from engine_py.db import get_session

        point = "NOW() - INTERVAL '1 minute'" if deadline == "past" else f"NOW() + INTERVAL '{deadline}'"
        async with get_session() as session:
            await session.execute(
                text(
                    "UPDATE threads SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), "
                    f"'{{takeover_release_at}}', to_jsonb({point})) WHERE id = :tid"
                ).bindparams(tid=thread_id)
            )
            await session.commit()


# ---------------------------------------------------------------------------
# ① 双写一致性
# ---------------------------------------------------------------------------


class TestTakeoverDualWrite:
    async def test_顾客呼叫_真源排队形态_工单退化为审计(self, client):
        tid, uid = await _mk_thread("dw_call")
        res = await client.post(
            "/api/chat/approvals",
            json={"action": "start_human_takeover", "threadId": tid, "userId": uid},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["success"] is True

        row = await _thread_row(tid)
        assert row["status"] == "human_takeover"
        assert row["assigned_operator_id"] is None  # 坐席空 = 呼叫中/排队
        assert row["requested"] is True  # 首记 requested_at(排队时长取最早呼叫)

        # 工单仍创建(human_escalation)但退化为审计,活态写真源
        from engine_py.db import get_session

        async with get_session() as session:
            ticket = (
                await session.execute(
                    text(
                        "SELECT action_type, status FROM pending_approvals "
                        "WHERE thread_id = :tid AND action_type = 'human_escalation'"
                    ).bindparams(tid=tid)
                )
            ).first()
        assert ticket is not None

    async def test_员工通道认领_真源落坐席(self, client, staff_auth):
        tid, uid = await _mk_thread("dw_claim")
        # 顾客先呼叫(排队形态)
        await client.post(
            "/api/chat/approvals", json={"action": "start_human_takeover", "threadId": tid, "userId": uid}
        )
        # 员工经商户管理面通道接管 = 认领
        res = await client.post(
            "/api/admin/approvals",
            json={"action": "start_human_takeover", "threadId": tid},
            headers=staff_auth,
        )
        assert res.status_code == 200
        assert res.json()["success"] is True

        row = await _thread_row(tid)
        assert row["status"] == "human_takeover"
        assert row["assigned_operator_id"] == STAFF_EMAIL

    async def test_坐席发言落operator列_无前缀_身份快照(self, client, staff_auth):
        tid, _uid = await _mk_thread("dw_msg")
        res = await client.post(
            "/api/admin/approvals",
            json={"action": "start_human_takeover", "threadId": tid},
            headers=staff_auth,
        )
        approval_id = res.json()["approvalId"]

        reply = f"您好，我是极光客服{_TS}"
        res2 = await client.post(
            "/api/admin/approvals",
            json={"approvalId": approval_id, "action": "human_reply", "replyMessage": reply, "isFinish": False},
            headers=staff_auth,
        )
        assert res2.status_code == 200
        body2 = res2.json()
        assert body2["success"] is True
        assert body2["isHumanActive"] is True

        operator_rows = [m for m in await _msgs(tid) if m["role"] == "operator"]
        assert len(operator_rows) == 1
        assert operator_rows[0]["content"] == reply  # 无 "[人工客服] " 前缀
        info = operator_rows[0]["operator_info"] or {}
        assert info.get("operatorId") == STAFF_EMAIL
        assert info.get("operatorName")  # 服务端派生,非空
        # 前缀拼接写侧退役:全程不得再落带前缀行(读侧兼容老数据是前端职责)
        assert await _count_msgs(tid, "[人工客服]") == 0

    async def test_释放写真源_active_系统提示恰一条(self, client, staff_auth):
        tid, _uid = await _mk_thread("dw_release")
        res = await client.post(
            "/api/admin/approvals",
            json={"action": "start_human_takeover", "threadId": tid},
            headers=staff_auth,
        )
        assert res.json()["success"] is True

        res2 = await client.post(
            "/api/admin/approvals", json={"action": "release_takeover", "threadId": tid}, headers=staff_auth
        )
        assert res2.status_code == 200
        body = res2.json()
        assert body["success"] is True
        assert body["released"] is True
        assert body["status"] == "active"

        row = await _thread_row(tid)
        assert row["status"] == "active"
        assert row["assigned_operator_id"] is None
        assert row["requested"] is False  # requested_at 随释放清除
        assert await _count_msgs(tid, "已成功为您切回 AI 智能助手") == 1


# ---------------------------------------------------------------------------
# ② AI 暂停闸(接管期不建作业;release 后恢复)
# ---------------------------------------------------------------------------


class TestPauseGate:
    async def test_接管期不建作业_用户行照常落库(self, client, staff_auth, monkeypatch):
        from engine_py.approvals import takeover

        # 拦截 run_agent(chat/merchant 两路由顶层绑定,patch 模块属性即生效):
        # 若闸失效,真引擎会在后台被拉起(封顶密封环境不可接受)
        async def _fake_run_agent(job):
            raise AssertionError("接管期不允许建作业/调引擎")

        monkeypatch.setattr("gateway_py.routers.chat.run_agent", _fake_run_agent)
        monkeypatch.setattr("gateway_py.routers.merchant.run_agent", _fake_run_agent)

        tid, uid = await _mk_thread("pg_pause")
        res = await client.post(
            "/api/admin/approvals",
            json={"action": "start_human_takeover", "threadId": tid},
            headers=staff_auth,
        )
        assert res.json()["success"] is True
        assert await takeover.is_human_takeover(tid) is True

        # 顾客入口①:dispatch_chat(异步建作业链)
        res2 = await client.post(
            "/api/chat",
            json={"message": "还在吗", "threadId": tid, "userId": uid, "businessId": "aurora"},
        )
        assert res2.status_code == 200
        body2 = res2.json()
        assert body2["success"] is True
        assert body2["jobId"] == ""  # 诚实:无作业
        assert body2["isHumanActive"] is True

        # 顾客入口②:store_chat(商户门户直跑链),同闸同文案
        res3 = await client.post(
            "/api/store/chat",
            json={"message": "人工在吗", "threadId": tid, "userId": uid, "businessId": "aurora"},
        )
        assert res3.status_code == 200
        body3 = res3.json()
        assert body3["jobId"] == ""
        assert body3["isHumanActive"] is True
        assert body3["output"] == "您的消息已由人工客服接待，请稍候人工坐席回复。"
        assert body3["cards"] == []

        # sync 直跑链同闸
        res4 = await client.post(
            "/api/chat",
            json={"message": "同步链也要闸", "threadId": tid, "userId": uid, "businessId": "aurora", "sync": True},
        )
        body4 = res4.json()
        assert body4["jobId"] == ""
        assert body4["isHumanActive"] is True
        assert "智能客服已为您处理完毕" not in (body4.get("output") or "")

        # 用户行照常落库(三条轮次全在,闸不吞消息)
        user_rows = [m for m in await _msgs(tid) if m["role"] == "user"]
        assert len(user_rows) == 3

    async def test_release后恢复建作业(self, client, staff_auth, monkeypatch):
        tid, uid = await _mk_thread("pg_resume")
        await client.post(
            "/api/admin/approvals",
            json={"action": "start_human_takeover", "threadId": tid},
            headers=staff_auth,
        )

        async def _fake_run_agent(job):
            return {"output": "AI 已恢复接管"}

        monkeypatch.setattr("gateway_py.routers.chat.run_agent", _fake_run_agent)

        # 释放前:闸住
        res = await client.post(
            "/api/chat", json={"message": "第一条", "threadId": tid, "userId": uid, "businessId": "aurora"}
        )
        assert res.json()["jobId"] == ""

        # 释放
        res2 = await client.post(
            "/api/admin/approvals", json={"action": "release_takeover", "threadId": tid}, headers=staff_auth
        )
        assert res2.json()["released"] is True

        # 释放后:下一条自然走 AI(建作业,无 isHumanActive 标记)
        res3 = await client.post(
            "/api/chat", json={"message": "第二条", "threadId": tid, "userId": uid, "businessId": "aurora"}
        )
        assert res3.status_code == 200
        body3 = res3.json()
        assert body3["success"] is True
        assert body3["jobId"]  # 恢供建作业
        assert not body3.get("isHumanActive")


# ---------------------------------------------------------------------------
# ③ 掉线超时释放(DB deadline + 幂等扫描为权威)
# ---------------------------------------------------------------------------


class TestTakeoverReleaseTimeoutScan:
    async def test_过期deadline_扫描释放_重复扫描零行(self, client):
        from engine_py.approvals import takeover

        tid, _uid = await _mk_thread("to_expired", business_id="nike")
        await _force_takeover(tid, "op-expired", deadline="past")

        released = await takeover.release_expired_takeovers()
        assert tid in released  # 宽容并发:同库其余过期会话被一并释放属正常

        row = await _thread_row(tid)
        assert row["status"] == "active"
        assert row["assigned_operator_id"] is None
        assert row["deadline"] is None
        assert await _count_msgs(tid, "暂时离线超时") == 1

        # 幂等:重复扫描 0 行,系统提示不重复落
        assert await takeover.release_expired_takeovers() == []
        assert await _count_msgs(tid, "暂时离线超时") == 1

    async def test_未来deadline与排队态不释放(self, client):
        from engine_py.approvals import takeover

        tid_future, _u1 = await _mk_thread("to_future", business_id="nike")
        await _force_takeover(tid_future, "op-future", deadline="1 hour")
        tid_queuing, _u2 = await _mk_thread("to_queue", business_id="nike")
        await _force_takeover(tid_queuing, None, deadline="past")  # 坐席空 = 排队,不扫

        released = await takeover.release_expired_takeovers()
        assert tid_future not in released
        assert tid_queuing not in released

        assert (await _thread_row(tid_future))["status"] == "human_takeover"
        assert (await _thread_row(tid_queuing))["status"] == "human_takeover"

    async def test_掉线写deadline仅首次生效_重连取消后可起新期(self, client):
        from engine_py.approvals import takeover

        tid, _uid = await _mk_thread("to_deadline", business_id="nike")
        await _force_takeover(tid, "op-dl")

        op_email = "op-dl@nike.test"
        assert await takeover.mark_disconnect_deadlines(op_email, 90) == 0  # 非其名下
        await takeover.assign_operator(tid, op_email)
        assert await takeover.mark_disconnect_deadlines(op_email, 90) == 1
        first = (await _thread_row(tid))["deadline"]

        # 仅首次生效:重连前的重复掉线不刷新计时
        assert await takeover.mark_disconnect_deadlines(op_email, 90) == 0
        assert (await _thread_row(tid))["deadline"] == first

        # 重连信号(join/认领/发言)取消;再次掉线才起新计时
        assert await takeover.cancel_disconnect_deadlines(op_email) == 1
        assert (await _thread_row(tid))["deadline"] is None
        assert await takeover.cancel_disconnect_deadlines(op_email) == 0  # 幂等
        assert await takeover.mark_disconnect_deadlines(op_email, 90) == 1
        assert (await _thread_row(tid))["deadline"] is not None


# ---------------------------------------------------------------------------
# ④ release_takeover 语义
# ---------------------------------------------------------------------------


class TestReleaseTakeoverSemantics:
    async def test_缺threadId_400(self, client, staff_auth):
        res = await client.post("/api/admin/approvals", json={"action": "release_takeover"}, headers=staff_auth)
        assert res.status_code == 400
        body = res.json()
        assert body["success"] is False
        assert "threadId" in body["error"]

    async def test_跨租户释放403_真源不动_双通道(self, client, staff_auth):
        tid, _uid = await _mk_thread("rel_cross", business_id="nike")
        await _force_takeover(tid, "op-nike@nike.test")

        # 商户管理面通道
        res = await client.post(
            "/api/admin/approvals", json={"action": "release_takeover", "threadId": tid}, headers=staff_auth
        )
        assert res.status_code == 403
        assert res.json()["success"] is False

        # chat 面员工通道(纵深防御,同一校验两处落地)
        res2 = await client.post(
            "/api/chat/approvals", json={"action": "release_takeover", "threadId": tid}, headers=staff_auth
        )
        assert res2.status_code == 403

        row = await _thread_row(tid)
        assert row["status"] == "human_takeover"  # 真源分毫未动
        assert row["assigned_operator_id"] == "op-nike@nike.test"

    async def test_重复释放幂等_不重复落系统消息(self, client, staff_auth):
        tid, _uid = await _mk_thread("rel_idem")
        await client.post(
            "/api/admin/approvals",
            json={"action": "start_human_takeover", "threadId": tid},
            headers=staff_auth,
        )
        res1 = await client.post(
            "/api/admin/approvals", json={"action": "release_takeover", "threadId": tid}, headers=staff_auth
        )
        res2 = await client.post(
            "/api/admin/approvals", json={"action": "release_takeover", "threadId": tid}, headers=staff_auth
        )
        assert res1.json()["released"] is True
        assert res2.status_code == 200
        assert res2.json()["released"] is False  # 0 行,诚实回报
        assert await _count_msgs(tid, "已成功为您切回 AI 智能助手") == 1

    async def test_未知线程释放_fail_open诚实无副作用(self, client, staff_auth):
        res = await client.post(
            "/api/admin/approvals",
            json={"action": "release_takeover", "threadId": f"rel_ghost_{uuid.uuid4().hex[:6]}"},
            headers=staff_auth,
        )
        assert res.status_code == 200
        assert res.json()["released"] is False
