"""坐席台独立页路由(live-desk-rework P2/P3;冻结面外新增,同批 pytest 契约钉死)。

P2 范围:坐席在线态读(presence)+ 免打扰自拨;P3 扩 `/threads/{id}/context`
聚合端点(坐席上下文栏五项,spec §2.4)与内部备注增删。
鉴权统一 Bearer JWT → 在职员工(0013 身份模型,租户由员工行带出,
不收客户端租户参数);按钮闸 `live_desk:operate` 照 order:ship 的
perms_for_role 先例(角色管理页勾选即生效)。
"""

from __future__ import annotations

import json
import uuid as _uuid

from engine_py.analytics import rbac
from engine_py.approvals import presence
from engine_py.db import AfterSaleTicket, LongMemoryFact, StaffMember, Thread, get_session
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .auth import require_claims

router = APIRouter()

_PERM_DENIED = {"success": False, "message": "无坐席操作权限(live_desk:operate)"}


async def _require_operate_staff(authorization: str | None):
    """Bearer JWT → 在职员工;须持 live_desk:operate。返回 (staff, None) 或
    (None, JSONResponse);401/403 语义与 merchant._require_staff 同模型。"""
    claims = await require_claims(authorization)
    email = str(claims.get("email") or "")
    async with get_session() as session:
        staff = (
            await session.execute(select(StaffMember).where(StaffMember.email == email))
        ).scalars().first()
    if staff is None or staff.status != "enabled":
        raise HTTPException(status_code=403, detail="非商户员工或已停用")
    if "live_desk:operate" not in await rbac.perms_for_role(staff.business_id, staff.role):
        return None, JSONResponse(status_code=403, content=_PERM_DENIED)
    return staff, None


@router.get("/api/merchant/live-desk/presence")
async def live_desk_presence(authorization: str | None = Header(None)):
    """坐席在线态汇总:在职员工行 ⨝ Redis presence(在线 ZSET + 免打扰 SET)。
    在线态仅展示、不作分配闸(spec §2.3);Redis 不可用时全员如实报离线。"""
    try:
        staff, denied = await _require_operate_staff(authorization)
        if denied is not None:
            return denied
        pmap = await presence.presence_map(staff.business_id)
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(StaffMember).where(
                        StaffMember.business_id == staff.business_id, StaffMember.status == "enabled"
                    )
                )
            ).scalars().all()
        agents = [
            {
                "email": s.email,
                "name": s.display_name,
                "role": s.role,
                "online": bool(pmap.get(s.email, {}).get("online")),
                "dnd": bool(pmap.get(s.email, {}).get("dnd")),
                "lastSeenAt": pmap.get(s.email, {}).get("lastSeenAt"),
            }
            for s in rows
        ]
        return {"success": True, "tenantId": staff.business_id, "agents": agents}
    except HTTPException:
        raise
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "message": str(err)})


@router.post("/api/merchant/live-desk/presence/dnd")
async def live_desk_dnd(body: dict, authorization: str | None = Header(None)):
    """免打扰自拨(工作台头部开关;手动状态无 TTL,再点关闭)。"""
    try:
        staff, denied = await _require_operate_staff(authorization)
        if denied is not None:
            return denied
        enabled = bool(body.get("enabled"))
        await presence.set_dnd(staff.business_id, staff.email, enabled)
        return {"success": True, "email": staff.email, "dnd": enabled}
    except HTTPException:
        raise
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "message": str(err)})


# ---------------- 坐席上下文栏(P3,spec §2.4):五项一次性聚合 ----------------

# 售后终态枚举(建单初始 pending_review,见 mall_domain 提交售后);非终态即「售后中」
_AFTER_SALE_CLOSED = ("completed", "rejected", "cancelled")
_PROFILE_LIMIT = 6
_ORDERS_LIMIT = 5
_TICKETS_LIMIT = 5


class NoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


def _mask_phone(phone: str | None) -> str | None:
    """坐席栏手机脱敏(138****8000):前 3 后 4,非 11 位只露后 4。"""
    if not phone:
        return None
    digits = phone.strip()
    if len(digits) >= 8:
        return f"{digits[:3]}****{digits[-4:]}"
    return f"****{digits[-4:]}" if digits else None


async def _load_thread_scoped(thread_id: str, tenant: str) -> Thread:
    """线程须存在(404)且属本租户(403;租户由 staff 行带,不信客户端)。"""
    async with get_session() as session:
        th = (await session.execute(select(Thread).where(Thread.id == thread_id))).scalars().first()
    if th is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if th.business_id != tenant:
        raise HTTPException(status_code=403, detail="会话不属于当前商户")
    return th


@router.get("/api/merchant/live-desk/threads/{thread_id}/context")
async def live_desk_thread_context(thread_id: str, authorization: str | None = Header(None)):
    """坐席上下文五项一次聚合(spec §2.4 最小闭环,单次往返零扇出):

    客户档案 / 最近订单 ≤5(merchant 库,关联键 chat userId ↔ customer_id
    **弱关联**:现网两域身份无桥,直等匹配不上即如实 `matched:false`,严禁编造)
    + 售后中工单 / 双层画像摘要(engine 库,与 chat user_id 同域,可靠)
    + 内部备注(thread_notes,仅坐席可见)。

    画像租户隔离照旧:global 栏全平台通用,tenant 栏严格本租户 business_id。
    """
    try:
        staff, denied = await _require_operate_staff(authorization)
        if denied is not None:
            return denied
        tenant = staff.business_id
        th = await _load_thread_scoped(thread_id, tenant)
        user_id = th.user_id or ""

        # engine 库同域直查:售后中工单 + 双层画像
        async with get_session() as session:
            tickets = (
                (
                    await session.execute(
                        select(AfterSaleTicket)
                        .where(
                            AfterSaleTicket.business_id == tenant,
                            AfterSaleTicket.user_id == user_id,
                            AfterSaleTicket.status.notin_(_AFTER_SALE_CLOSED),
                        )
                        .order_by(AfterSaleTicket.created_at.desc())
                        .limit(_TICKETS_LIMIT)
                    )
                )
                .scalars()
                .all()
                if user_id
                else []
            )
            facts = (
                (
                    await session.execute(
                        select(LongMemoryFact)
                        .where(
                            LongMemoryFact.user_id == user_id,
                            LongMemoryFact.status == "approved",
                            (LongMemoryFact.scope == "global")
                            | ((LongMemoryFact.scope == "tenant") & (LongMemoryFact.business_id == tenant)),
                        )
                        .order_by(LongMemoryFact.created_at.desc())
                        .limit(_PROFILE_LIMIT * 2)
                    )
                )
                .scalars()
                .all()
                if user_id
                else []
            )

        profile_global = [f.fact for f in facts if f.scope == "global"][:_PROFILE_LIMIT]
        profile_tenant = [f.fact for f in facts if f.scope == "tenant"][:_PROFILE_LIMIT]

        # merchant 库:弱关联直等试配 + 命中时档案/订单;未匹配如实空(不编造)
        from engine_py.tools_registry.order_domain import merchant_reader_engine
        from sqlalchemy import text as _text

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()  # 懒自愈先例(merchant_domain 同款);首次后短路
        customer = {"matched": False}
        recent_orders: list[dict] = []
        notes: list[dict] = []
        async with merchant_reader_engine().connect() as conn:
            if user_id:
                row = (
                    await conn.execute(
                        _text(
                            "SELECT c.customer_id, c.name, c.phone, COALESCE(c.email,'') AS email, "
                            "c.member_level, COALESCE(c.tags,'[]'::jsonb)::text AS tags, "
                            "COALESCE(SUM(o.total_amount),0)::float AS total_spent, "
                            "COUNT(o.order_id)::int AS order_count "
                            "FROM merchant_customers c LEFT JOIN merchant_orders o ON o.customer_id = c.customer_id "
                            "WHERE c.customer_id = :cid GROUP BY c.id"
                        ),
                        {"cid": user_id},
                    )
                ).mappings().first()
                if row is not None:
                    customer = {
                        "matched": True,
                        "customerId": row["customer_id"],
                        "name": row["name"],
                        "phoneMasked": _mask_phone(row["phone"]),
                        "email": row["email"],
                        "memberLevel": row["member_level"],
                        "tags": json.loads(row["tags"]) if row["tags"] else [],
                        "totalSpent": row["total_spent"],
                        "orderCount": row["order_count"],
                    }
                    recent_orders = [
                        dict(r)
                        for r in (
                            await conn.execute(
                                _text(
                                    "SELECT order_id AS \"orderId\", status, total_amount AS \"totalAmount\", created_at "
                                    "FROM merchant_orders WHERE customer_id = :cid "
                                    "ORDER BY created_at DESC LIMIT :lim"
                                ),
                                {"cid": user_id, "lim": _ORDERS_LIMIT},
                            )
                        ).mappings()
                    ]
            notes = [
                {
                    "id": str(r["id"]),
                    "content": r["content"],
                    "authorEmail": r["author_email"],
                    "createdAt": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in (
                    await conn.execute(
                        _text(
                            "SELECT id, content, author_email, created_at FROM thread_notes "
                            "WHERE thread_id = :tid AND business_id = :bid ORDER BY created_at DESC LIMIT 50"
                        ),
                        {"tid": thread_id, "bid": tenant},
                    )
                ).mappings()
            ]

        for o in recent_orders:
            if o.get("created_at") is not None:
                o["createdAt"] = o.pop("created_at").isoformat()

        return {
            "success": True,
            "thread": {
                "threadId": th.id,
                "userId": th.user_id,
                "status": th.status,
                "assignedOperatorId": th.assigned_operator_id,
            },
            "customer": customer,
            "recentOrders": recent_orders,
            "afterSaleTickets": [
                {
                    "id": t.id,
                    "orderId": t.order_id,
                    "type": t.type,
                    "reason": t.reason,
                    "status": t.status,
                    "refundAmount": t.refund_amount,
                    "createdAt": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tickets
            ],
            "profile": {"global": profile_global, "tenant": profile_tenant},
            "notes": notes,
        }
    except HTTPException:
        raise
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "message": str(err)})


@router.post("/api/merchant/live-desk/threads/{thread_id}/notes")
async def live_desk_note_create(thread_id: str, body: NoteCreate, authorization: str | None = Header(None)):
    """坐席内部备注新增(仅 agent_merchant.thread_notes,顾客链路物理触不到)。"""
    try:
        staff, denied = await _require_operate_staff(authorization)
        if denied is not None:
            return denied
        tenant = staff.business_id
        await _load_thread_scoped(thread_id, tenant)

        from engine_py.tools_registry.order_domain import merchant_writer_engine
        from sqlalchemy import text as _text

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        # 写穿透走 writer(reader 带会话级 READ ONLY,INSERT 必被只读事务拒绝)
        async with merchant_writer_engine().begin() as conn:
            row = (
                await conn.execute(
                    _text(
                        "INSERT INTO thread_notes (thread_id, business_id, author_email, content) "
                        "VALUES (:tid, :bid, :author, :content) RETURNING id, created_at"
                    ),
                    {"tid": thread_id, "bid": tenant, "author": staff.email, "content": body.content.strip()},
                )
            ).mappings().first()
        return {
            "success": True,
            "note": {
                "id": str(row["id"]),
                "content": body.content.strip(),
                "authorEmail": staff.email,
                "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
            },
        }
    except HTTPException:
        raise
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "message": str(err)})


@router.delete("/api/merchant/live-desk/threads/{thread_id}/notes/{note_id}")
async def live_desk_note_delete(thread_id: str, note_id: str, authorization: str | None = Header(None)):
    """备注删除(幂等:重复删 0 行仍 success,不改语义)。"""
    try:
        staff, denied = await _require_operate_staff(authorization)
        if denied is not None:
            return denied
        tenant = staff.business_id
        await _load_thread_scoped(thread_id, tenant)
        try:
            note_uuid = str(_uuid.UUID(note_id))
        except ValueError:
            return {"success": True}  # 非法 uuid 当查无,幂等不炸

        from engine_py.tools_registry.order_domain import merchant_writer_engine
        from sqlalchemy import text as _text

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        async with merchant_writer_engine().begin() as conn:
            await conn.execute(
                _text("DELETE FROM thread_notes WHERE id = CAST(:nid AS uuid) AND thread_id = :tid AND business_id = :bid"),
                {"nid": note_uuid, "tid": thread_id, "bid": tenant},
            )
        return {"success": True}
    except HTTPException:
        raise
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "message": str(err)})
