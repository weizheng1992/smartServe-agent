"""P3 坐席上下文栏契约(live-desk-rework spec §3 P3 行)。

① 鉴权矩阵:匿名 401 / 员工同租户持 operate 200 / 跨租户 403 / 查无 404 /
   无 operate perm 403(perm 闸语义与 P2 三态同源)。
② 五项形状:档案(弱关联命中:matched+脱敏手机+消费聚合)/ 最近订单 ≤5 /
   售后中工单(终态不出现)/ 双层画像(global|tenant 分栏,他租户事实不出现)/
   内部备注。
③ 弱关联诚实:chat userId ↔ merchant customer_id 无桥时 matched:false,
   recentOrders 空 —— 严禁编造(spec §2.4 实施首项核实结论)。
④ notes 幂等与隔离:重复删除幂等成真;非法 uuid 幂等成真;跨租户读不到。
⑤ notes 不出现在任何顾客响应:顾客历史/会话列表全链文本不含备注内容
   (「不外发靠构造」的回归钉)。
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import _TS, create_thread

pytestmark = pytest.mark.usefixtures("seeded")

STAFF_EMAIL = "test@example.com"  # staff_auth = aurora finance_owner(兜底全量)


async def _mk_thread(prefix: str, business_id: str = "aurora", user_id: str | None = None) -> tuple[str, str]:
    tid = f"{prefix}_{_TS}_{uuid.uuid4().hex[:6]}"
    uid = user_id or f"u_{prefix}_{uuid.uuid4().hex[:6]}"
    await create_thread(tid, uid, business_id)
    return tid, uid


async def _merchant_exec(stmt: str, params: dict | None = None, write: bool = False):
    from engine_py.tools_registry.order_domain import _merchant_reader_engine, _merchant_writer_engine
    from sqlalchemy import text as _text

    engine = _merchant_writer_engine() if write else _merchant_reader_engine()
    async with (engine.begin() if write else engine.connect()) as conn:
        if write:
            await conn.execute(_text(stmt), params or {})
        else:
            return (await conn.execute(_text(stmt), params or {})).mappings().all()


async def _seed_customer_with_orders(uid: str) -> None:
    """弱关联命中路径造数:merchant 档案/订单的 customer_id 直等 chat userId。
    (现网两域身份无桥,唯商城顾客以 customer_id 作聊天身份时命中 —— 造数同形)"""
    from gateway_py.merchant_db import ensure_merchant_tables

    await ensure_merchant_tables()  # 幂等 DDL(含 thread_notes,P3 起随启动自愈)
    await _merchant_exec(
        "INSERT INTO merchant_customers (customer_id, name, phone, member_level, tags) "
        "VALUES (:cid, '测试顾客', '13800138000', 'VIP', '[\"高净值客户\"]'::jsonb) "
        "ON CONFLICT (customer_id) DO NOTHING",
        {"cid": uid},
        write=True,
    )
    for i, (status, amount) in enumerate([("SHIPPED", 299.0), ("COMPLETED", 159.5)]):
        await _merchant_exec(
            "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, "
            "shipping_address, created_at) VALUES (:oid, :cid, :st, :amt, "
            "'{\"city\":\"测试市\"}'::jsonb, NOW() - make_interval(hours => :h))",
            {"oid": f"ORD-{uid[-8:]}-{i}", "cid": uid, "st": status, "amt": amount, "h": i * 24},
            write=True,
        )


async def _seed_fact(uid: str, scope: str, business_id: str | None, fact: str) -> None:
    from engine_py.db import LongMemoryFact, get_session

    async with get_session() as session:
        session.add(LongMemoryFact(
            id=uuid.uuid4(), user_id=uid, business_id=business_id, scope=scope,
            fact=fact, status="approved", source="chat_dialogue_inference",
        ))
        await session.commit()


async def _seed_ticket(uid: str, status: str) -> str:
    from engine_py.db import AfterSaleTicket, get_session

    ticket_id = f"ast_{_TS}_{uuid.uuid4().hex[:8]}"
    async with get_session() as session:
        session.add(AfterSaleTicket(
            id=ticket_id, business_id="aurora", order_id=f"ORD-{uid[-8:]}", user_id=uid,
            type="refund", reason="质量问题", refund_amount=99.0, status=status,
        ))
        await session.commit()
    return ticket_id


async def _issue_staff(role: str, business_id: str = "aurora") -> dict:
    """直签任意角色的 aurora 员工(perms 走 role_menus 闭包)。"""
    from engine_py.db import StaffMember, get_session

    from gateway_py.routers.auth import issue_token

    email = f"{role.replace('_', '')}-{_TS}-{uuid.uuid4().hex[:4]}@aurora.test"
    sid = f"staff_{_TS}_{uuid.uuid4().hex[:6]}"
    async with get_session() as session:
        session.add(StaffMember(
            id=sid, business_id=business_id, email=email, display_name=email,
            role=role, status="enabled", password_hash=None,
        ))
        await session.commit()
    return {"Authorization": f"Bearer {issue_token(sid, email)}", "email": email}


class TestContextAuthMatrix:
    async def test_匿名401(self, client):
        r = await client.get("/api/merchant/live-desk/threads/whatever/context")
        assert r.status_code == 401

    async def test_员工同租户200_五项形状齐(self, client, staff_auth):
        tid, uid = await _mk_thread("ctx_ok")
        await _seed_customer_with_orders(uid)
        await _seed_fact(uid, "global", None, "偏好棉质面料(全局)")
        await _seed_fact(uid, "tenant", "aurora", "偏好基础款(本店)")
        await _seed_fact(uid, "tenant", "nike", "耐克偏好不得出现")
        await _seed_ticket(uid, "pending_review")
        await _seed_ticket(uid, "completed")  # 终态不出现

        r = await client.get(
            f"/api/merchant/live-desk/threads/{tid}/context", headers=staff_auth
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["thread"]["threadId"] == tid
        # 档案:弱关联命中 + 手机脱敏 + 聚合
        assert body["customer"]["matched"] is True
        assert body["customer"]["name"] == "测试顾客"
        assert body["customer"]["phoneMasked"] == "138****8000"
        assert body["customer"]["orderCount"] == 2
        # 最近订单 ≤5,camelCase
        assert len(body["recentOrders"]) == 2
        assert {"orderId", "status", "totalAmount", "createdAt"} <= set(body["recentOrders"][0])
        # 售后中:仅非终态
        assert len(body["afterSaleTickets"]) == 1
        assert body["afterSaleTickets"][0]["status"] == "pending_review"
        # 双层画像分栏 + 租户隔离(nike 事实不得出现)
        assert body["profile"]["global"] == ["偏好棉质面料(全局)"]
        assert body["profile"]["tenant"] == ["偏好基础款(本店)"]
        # notes 初始空数组(形状齐)
        assert body["notes"] == []

    async def test_跨租户403_查无404(self, client, staff_auth, nike_operator):
        tid, _ = await _mk_thread("ctx_cross")
        # nike 员工访问 aurora 线程
        r = await client.get(
            f"/api/merchant/live-desk/threads/{tid}/context",
            headers={"Authorization": f"Bearer {nike_operator['token']}"},
        )
        assert r.status_code == 403
        # aurora 员工访问不存在的线程
        r2 = await client.get(
            f"/api/merchant/live-desk/threads/no_such_thread_{_TS}/context", headers=staff_auth
        )
        assert r2.status_code == 404

    async def test_无operate_perm403(self, client, staff_auth):
        tid, _ = await _mk_thread("ctx_perm")
        wh = await _issue_staff("warehouse_operator")
        r = await client.get(
            f"/api/merchant/live-desk/threads/{tid}/context", headers=wh
        )
        assert r.status_code == 403
        assert "无坐席操作权限" in r.json()["message"]


class TestWeakLinkHonesty:
    async def test_无档案如实未匹配(self, client, staff_auth):
        tid, _uid = await _mk_thread("ctx_nomatch")
        r = await client.get(
            f"/api/merchant/live-desk/threads/{tid}/context", headers=staff_auth
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["customer"]["matched"] is False
        assert body["recentOrders"] == []
        # 同域面照常(不因档案未匹配而编造或整栏报错)
        assert body["profile"]["global"] == []
        assert body["profile"]["tenant"] == []


class TestNotes:
    async def test_增查删_重复删幂等_非法uuid幂等(self, client, staff_auth):
        tid, _ = await _mk_thread("ctx_notes")
        marker = f"顾客抱怨物流慢,已安抚_{_TS}"
        r = await client.post(
            f"/api/merchant/live-desk/threads/{tid}/notes",
            headers=staff_auth, json={"content": marker},
        )
        assert r.status_code == 200, r.text
        note = r.json()["note"]
        assert note["content"] == marker
        assert note["authorEmail"] == STAFF_EMAIL

        ctx = (
            await client.get(f"/api/merchant/live-desk/threads/{tid}/context", headers=staff_auth)
        ).json()
        assert [n["content"] for n in ctx["notes"]] == [marker]

        for _ in range(2):  # 重复删幂等
            rd = await client.delete(
                f"/api/merchant/live-desk/threads/{tid}/notes/{note['id']}", headers=staff_auth
            )
            assert rd.status_code == 200 and rd.json()["success"] is True
        bad = await client.delete(
            f"/api/merchant/live-desk/threads/{tid}/notes/not-a-uuid", headers=staff_auth
        )
        assert bad.status_code == 200  # 非法 uuid 当查无,不炸

        ctx2 = (
            await client.get(f"/api/merchant/live-desk/threads/{tid}/context", headers=staff_auth)
        ).json()
        assert ctx2["notes"] == []

    async def test_备注不外发任何顾客响应(self, client, staff_auth):
        tid, uid = await _mk_thread("ctx_leak")
        marker = f"内部备注防泄漏标记_{_TS}_{uuid.uuid4().hex[:6]}"
        r = await client.post(
            f"/api/merchant/live-desk/threads/{tid}/notes",
            headers=staff_auth, json={"content": marker},
        )
        assert r.status_code == 200, r.text
        # 顾客面全链:历史消息(匿名过渡语义)/ 会话列表 / 线程列表,响应文本均不含备注
        leak_faces = [
            ("/api/chat/messages", {"params": {"threadId": tid, "userId": uid}}),
            ("/api/conversations", {"params": {}}),
            ("/api/chat/threads", {"params": {"userId": uid}}),
        ]
        for path, kw in leak_faces:
            resp = await client.get(path, params=kw.get("params"))
            assert marker not in resp.text, f"{path} 泄漏内部备注"


class TestDdlIdempotent:
    async def test_ensure_merchant_tables重复执行不炸(self):
        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        await ensure_merchant_tables()  # 启动自愈路径幂等(thread_notes 随批)
        rows = await _merchant_exec(
            "SELECT COUNT(*) AS n FROM thread_notes"
        )
        assert rows[0]["n"] >= 0
