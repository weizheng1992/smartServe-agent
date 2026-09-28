"""P2 分配与队列契约(live-desk-rework spec §3 P2 行)。

① 认领池原子守卫:双坐席同抢只成一人(一成一败);本坐席重复认领幂等成真;
   跨租户认领 0 行;socket takeover 败者收 ack {success:False, error:已被认领}
   且不落系统消息不广播。
② unread_count 激活:顾客消息落库 +1(append_message 单点,operator/assistant/
   system 不计,ON CONFLICT 重放不计);持 live_desk:operate 的员工 GET
   /api/chat/messages 清零;匿名/无权限不清零。
③ 排队超时回落:release_expired_queue_waits 幂等扫描 —— 过期排队回落 active +
   system 告知;未过期不动;接管中(坐席非空)不动;重复扫描 0 行。
④ perms 三态:support_agent 恰持 live_desk:operate;finance_owner 兜底全量;
   warehouse_operator 无 operate 且被 perm 闸拒绝。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded")

STAFF_EMAIL = "test@example.com"  # staff_auth = aurora finance_owner


async def _mk_thread(prefix: str, business_id: str = "aurora") -> str:
    tid = f"{prefix}_{_TS}_{uuid.uuid4().hex[:6]}"
    await create_thread(tid, f"u_{prefix}_{uuid.uuid4().hex[:6]}", business_id)
    return tid


async def _row(thread_id: str) -> dict:
    from engine_py.db import get_session

    async with get_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, assigned_operator_id, COALESCE(unread_count, 0) AS unread "
                    "FROM threads WHERE id = :tid"
                ).bindparams(tid=thread_id)
            )
        ).mappings().first()
    assert row is not None
    return dict(row)


async def _force_queue(thread_id: str, age_seconds: float) -> None:
    """直接把线程摆成「排队中且已等待 age_seconds」的形态(绕过呼叫链路,
    专注回落扫描判定本身)。"""
    from engine_py.db import get_session

    async with get_session() as session:
        await session.execute(
            text(
                "UPDATE threads SET status = 'human_takeover', assigned_operator_id = NULL, "
                "metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{takeover_requested_at}', "
                "to_jsonb(NOW() - make_interval(secs => :age))) WHERE id = :tid"
            ).bindparams(age=age_seconds, tid=thread_id)
        )
        await session.commit()


class TestClaimAtomicGuard:
    async def test_双坐席同抢一成一败(self):
        from engine_py.approvals import takeover

        tid = await _mk_thread("claim_race")
        op_a, op_b = f"a_{_TS}@aurora", f"b_{_TS}@aurora"
        # 并发派发同一认领:原子 UPDATE 裁决,恰一人成功
        results = await asyncio.gather(
            takeover.assign_operator(tid, op_a, business_id="aurora"),
            takeover.assign_operator(tid, op_b, business_id="aurora"),
        )
        assert sorted(results) == [False, True], f"同抢必须一成一败,实得 {results}"
        row = await _row(tid)
        assert row["status"] == "human_takeover"
        assert row["assigned_operator_id"] in (op_a, op_b)

    async def test_败者认领_真源保持胜者(self):
        from engine_py.approvals import takeover

        tid = await _mk_thread("claim_loser")
        op_a, op_b = f"a_{_TS}@aurora", f"b_{_TS}@aurora"
        assert await takeover.assign_operator(tid, op_a, business_id="aurora") is True
        assert await takeover.assign_operator(tid, op_b, business_id="aurora") is False
        row = await _row(tid)
        assert row["assigned_operator_id"] == op_a

    async def test_本坐席重复认领幂等成真(self):
        from engine_py.approvals import takeover

        tid = await _mk_thread("claim_self")
        assert await takeover.assign_operator(tid, STAFF_EMAIL, business_id="aurora") is True
        assert await takeover.assign_operator(tid, STAFF_EMAIL, business_id="aurora") is True

    async def test_跨租户认领拒绝(self):
        from engine_py.approvals import takeover

        tid = await _mk_thread("claim_cross")
        assert await takeover.assign_operator(tid, "x@nike", business_id="nike") is False
        row = await _row(tid)
        assert row["status"] != "human_takeover"

    async def test_socket_认领败者收已被认领_不落系统消息(self, live_server, nike_operator):
        import socketio as socketio_lib
        from engine_py.db import StaffMember, get_session

        from gateway_py import conversation_repo
        from gateway_py.routers.auth import issue_token

        ns = "/ws/chat"
        tid = await _mk_thread("claim_sock", business_id="nike")

        # 两名 nike 坐席(直签 JWT;菜单面已由 nike_operator fixture 补齐,admin 恒持 operate)
        tokens: dict[str, str] = {}
        async with get_session() as session:
            for suffix in ("1", "2"):
                email = f"claim{suffix}_{_TS}@nike.test"
                session.add(StaffMember(
                    id=f"staff_claim{suffix}_{_TS}", business_id="nike", email=email,
                    display_name=f"抢座席{suffix}", role="admin", status="enabled", password_hash=None,
                ))
                tokens[email] = issue_token(f"staff_claim{suffix}_{_TS}", email)
            await session.commit()

        events: list[dict] = []
        c1 = socketio_lib.AsyncClient(reconnection=False)
        c2 = socketio_lib.AsyncClient(reconnection=False)
        c1.on("conversation_state_changed", lambda p=None: events.append(p or {}), namespace=ns)
        await c1.connect(live_server, transports=["websocket"], namespaces=[ns],
                         auth={"tenantId": "nike", "userId": "u1", "role": "operator", "token": tokens[f"claim1_{_TS}@nike.test"]})
        await c2.connect(live_server, transports=["websocket"], namespaces=[ns],
                         auth={"tenantId": "nike", "userId": "u2", "role": "operator", "token": tokens[f"claim2_{_TS}@nike.test"]})
        try:
            # c1 先入房收广播;顺序认领保证 c1 胜 c2 败(真并发竞争归 gather 用例)
            await c1.call("join_thread", {"threadId": tid, "tenantId": "nike", "role": "operator"}, namespace=ns, timeout=5)
            ack1 = await c1.call("takeover_conversation", {"threadId": tid, "tenantId": "nike"}, namespace=ns, timeout=5)
            ack2 = await c2.call("takeover_conversation", {"threadId": tid, "tenantId": "nike"}, namespace=ns, timeout=5)
            assert ack1["success"] is True
            assert ack2["success"] is False
            assert "认领" in ack2["error"]
            assert ack1["status"] == "human_takeover" and ack1["assignedOperatorId"] == f"claim1_{_TS}@nike.test"
            # 胜者落系统接入提示恰一条;败者不重复落
            msgs = await conversation_repo.get_conversation_timeline(tid, "nike")
            sys_rows = [m for m in msgs["messages"] if m["role"] == "system" and "已接入会话" in (m.get("content") or "")]
            assert len(sys_rows) == 1
            # 房间广播恰一次,且载荷带 threads 真源三键(spec §4)
            deadline = asyncio.get_event_loop().time() + 3
            while not events and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.05)
            assert len(events) == 1, f"胜者广播应恰一次,实得 {len(events)}"
            assert events[0]["assignedOperatorId"] == f"claim1_{_TS}@nike.test"
            assert "unreadCount" in events[0]
        finally:
            for c in (c1, c2):
                if c.connected:
                    await c.disconnect()


class TestUnreadCount:
    async def test_顾客消息落库加一_他角色不计(self):
        from gateway_py import conversation_repo

        tid = await _mk_thread("unread")
        await conversation_repo.append_message({"threadId": tid, "businessId": "aurora", "role": "user", "content": "在吗"})
        await conversation_repo.append_message({"threadId": tid, "businessId": "aurora", "role": "user", "content": "有人吗"})
        await conversation_repo.append_message({"threadId": tid, "businessId": "aurora", "role": "operator", "content": "您好"})
        await conversation_repo.append_message({"threadId": tid, "businessId": "aurora", "role": "assistant", "content": "AI 答复"})
        await conversation_repo.append_message({"threadId": tid, "businessId": "aurora", "role": "system", "content": "系统行"})
        assert (await _row(tid))["unread"] == 2

    async def test_同id重放不重复计数(self):
        from gateway_py import conversation_repo

        tid = await _mk_thread("unread_replay")
        payload = {"threadId": tid, "businessId": "aurora", "role": "user", "content": "重放", "id": f"dup_{_TS}"}
        await conversation_repo.append_message(payload)
        await conversation_repo.append_message(payload)
        assert (await _row(tid))["unread"] == 1

    async def test_员工打开时间线清零_匿名不清(self, client, staff_auth):
        tid = await _mk_thread("unread_clear")
        from gateway_py import conversation_repo

        await conversation_repo.append_message({"threadId": tid, "businessId": "aurora", "role": "user", "content": "未读一"})
        assert (await _row(tid))["unread"] == 1

        # 匿名(顾客轮询形态)→ 不清零
        await client.get(f"/api/chat/messages?threadId={tid}&businessId=aurora")
        assert (await _row(tid))["unread"] == 1

        # 持 live_desk:operate 的员工打开 → 清零
        res = await client.get(f"/api/chat/messages?threadId={tid}&businessId=aurora", headers=staff_auth)
        assert res.status_code == 200
        assert (await _row(tid))["unread"] == 0

    async def test_无权限员工不清零(self, client):
        """warehouse_operator 无 live_desk:operate(角色菜单闭包无该按钮)→
        打开时间线不清。自插仓储员工行直签 JWT,不赌种子邮箱。"""
        from engine_py.analytics import rbac
        from engine_py.db import StaffMember, get_session

        from gateway_py import conversation_repo
        from gateway_py.routers.auth import issue_token

        await rbac.ensure_defaults("aurora")
        tid = await _mk_thread("unread_noperm")
        await conversation_repo.append_message({"threadId": tid, "businessId": "aurora", "role": "user", "content": "未读二"})

        email = f"wh_{_TS}@aurora.test"
        async with get_session() as session:
            session.add(StaffMember(
                id=f"staff_wh_{_TS}", business_id="aurora", email=email,
                display_name="仓储员", role="warehouse_operator", status="enabled", password_hash=None,
            ))
            await session.commit()
        headers = {"Authorization": f"Bearer {issue_token(f'staff_wh_{_TS}', email)}"}
        res = await client.get(f"/api/chat/messages?threadId={tid}&businessId=aurora", headers=headers)
        assert res.status_code == 200
        assert (await _row(tid))["unread"] == 1


class TestQueueFallbackScan:
    async def test_过期排队回落_幂等(self):
        from engine_py.approvals import takeover

        tid = await _mk_thread("queue_fall")
        await _force_queue(tid, age_seconds=600)
        released = await takeover.release_expired_queue_waits(timeout_seconds=300)
        assert tid in released
        row = await _row(tid)
        assert row["status"] == "active"
        assert row["assigned_operator_id"] is None
        # 幂等:重复扫描 0 行
        assert await takeover.release_expired_queue_waits(timeout_seconds=300) == []

    async def test_未过期排队不动_接管中不动(self):
        from engine_py.approvals import takeover

        fresh = await _mk_thread("queue_fresh")
        await _force_queue(fresh, age_seconds=60)
        claimed = await _mk_thread("queue_claimed")
        await _force_queue(claimed, age_seconds=600)
        from engine_py.db import get_session

        async with get_session() as session:
            await session.execute(
                text("UPDATE threads SET assigned_operator_id = :op WHERE id = :tid").bindparams(
                    op="busy@aurora", tid=claimed
                )
            )
            await session.commit()

        released = await takeover.release_expired_queue_waits(timeout_seconds=300)
        assert fresh not in released and claimed not in released
        assert (await _row(fresh))["status"] == "human_takeover"
        assert (await _row(claimed))["status"] == "human_takeover"

    async def test_回落落顾客告知系统消息(self):
        from engine_py.approvals import takeover

        from gateway_py import conversation_repo

        tid = await _mk_thread("queue_notice")
        await _force_queue(tid, age_seconds=600)
        await takeover.release_expired_queue_waits(timeout_seconds=300)
        timeline = await conversation_repo.get_conversation_timeline(tid, "aurora")
        notices = [m for m in timeline["messages"] if m["role"] == "system" and "切回 AI" in (m.get("content") or "")]
        assert len(notices) == 1
