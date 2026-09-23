"""商户 data agent 路由组(09-D2;/api/admin/analytics/*)。

员工鉴权面(0013 收口):身份 = Bearer JWT 的 email claim → staff_members
(员工密码真实登录;不再信任 x-user-id 头,未识别员工 403 而非回落老板)。
按钮/指标权限按 role_menus 动态派生(rbac.perms_for_role,勾选即生效)。
轻管线直调 engine(analytics 包),不走 Temporal(15 号决议)。
SSE 帧:event: clarify|result|unsupported|error。
"""

from __future__ import annotations

import asyncio
import json

from engine_py.analytics import graph, promotions, rbac, report_service
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, select

from gateway_py.tenant_context import require_tenant_context

from .auth import issue_token, require_claims

router = APIRouter(tags=["merchant-analytics"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _ctx(request: Request) -> dict:
    """统一请求上下文:租户 + 员工身份(JWT)+ 角色 + 按钮权限点闭集。"""
    tc = require_tenant_context()
    claims = await require_claims(request.headers.get("authorization"))
    business_id = tc.get("tenantId") or "aurora"
    await rbac.ensure_defaults(business_id)
    staff = await rbac.find_staff(business_id, str(claims.get("email") or ""))
    if staff is None or staff.status != "enabled":
        raise HTTPException(status_code=403, detail="非商户员工或已停用,拒绝访问")
    return {
        "business_id": business_id,
        "role": staff.role,
        "staff": staff.email,
        "display": staff.display_name,
        "perms": await rbac.perms_for_role(business_id, staff.role),
    }


@router.post("/api/admin/analytics/ask")
async def analytics_ask(request: Request):
    """一轮问答 SSE:body {question, pageContext?};事件 clarify|result|unsupported|error。"""
    ctx = await _ctx(request)
    body = await request.json()
    question = str(body.get("question") or "").strip()
    if not question:
        return JSONResponse(status_code=400, content={"success": False, "message": "question 必传"})

    async def stream():
        yield _sse("start", {"staff": ctx["display"], "role": ctx["role"]})
        try:
            outcome = await graph.ask_all(question, ctx, body.get("pageContext"))
        except Exception as err:
            outcome = {"type": "error", "message": str(err)}
        if outcome.get("type") == "multi":
            # 场景包/问号切分:一轮回多帧,前端逐帧渲染(每帧独立导出/存报告)
            for frame in outcome.get("frames") or []:
                yield _sse(frame.get("type", "error"), frame)
        else:
            yield _sse(outcome.get("type", "error"), outcome)
        await asyncio.sleep(0)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
    })


@router.get("/api/admin/analytics/menus")
async def analytics_menus(request: Request):
    ctx = await _ctx(request)
    tree = await rbac.menu_tree_for_role(ctx["business_id"], ctx["role"])
    return {"success": True, "role": ctx["role"], "perms": ctx["perms"], "menus": tree}


@router.post("/api/admin/analytics/roles/{role}/menus")
async def set_role_menus(role: str, request: Request):
    """保存角色菜单+按钮权限分配(0013:按钮权限点随 role_menus 动态生效)。"""
    ctx = await _ctx(request)
    if role not in rbac.ROLES and not role.startswith("custom_"):
        return JSONResponse(status_code=400, content={"success": False, "message": f"未知角色 {role}"})
    if not rbac.is_manager(ctx["role"]):
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板/管理员可分配权限"})
    body = await request.json()
    await rbac.set_role_menus(ctx["business_id"], role, list(body.get("menuIds") or []), ctx["staff"])
    return {"success": True}


@router.get("/api/admin/analytics/roles/{role}/menus")
async def get_role_menus(role: str, request: Request):
    """角色当前权限分配明细(角色管理页勾选树回填)。"""
    ctx = await _ctx(request)
    if not rbac.is_manager(ctx["role"]):
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板/管理员可查看权限分配"})
    from engine_py.db import RoleMenu, get_session

    async with get_session() as session:
        rows = (
            await session.execute(
                select(RoleMenu).where(RoleMenu.role == role, RoleMenu.business_id == ctx["business_id"])
            )
        ).scalars().all()
    return {"success": True, "role": role, "menuIds": sorted(r.menu_id for r in rows)}


@router.get("/api/admin/analytics/staff")
async def analytics_staff(request: Request):
    from engine_py.db import StaffMember, get_session
    from sqlalchemy import select

    ctx = await _ctx(request)
    async with get_session() as session:
        rows = (await session.execute(
            select(StaffMember).where(StaffMember.business_id == ctx["business_id"])
        )).scalars().all()
    return {"success": True, "staff": [
        {"id": r.id, "email": r.email, "displayName": r.display_name, "role": r.role, "status": r.status}
        for r in rows
    ]}


@router.post("/api/admin/analytics/staff/switch")
async def switch_account(request: Request):
    """老板快捷切换身份(0013 收口):切换 = 服务端为目标员工签发 JWT,
    前端换 token 后即以该员工身份行事;非老板 403(旧实现任意 staffId 可
    自报身份,已随 x-user-id 信任一并拆除)。"""
    ctx = await _ctx(request)
    if not rbac.is_manager(ctx["role"]):
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板/管理员可切换查看身份"})
    body = await request.json()
    target = str(body.get("staffId") or "").strip()
    if not target:
        return JSONResponse(status_code=400, content={"success": False, "message": "staffId 必传"})
    staff = await rbac.find_staff(ctx["business_id"], target)
    if staff is None or staff.status != "enabled":
        return JSONResponse(status_code=404, content={"success": False, "message": "员工不存在或已停用"})
    tree = await rbac.menu_tree_for_role(ctx["business_id"], staff.role)
    return {
        "success": True,
        "staffId": staff.email,
        "displayName": staff.display_name,
        "role": staff.role,
        "menus": tree,
        "token": issue_token(staff.id, staff.email),
    }


@router.get("/api/admin/analytics/reports")
async def analytics_reports(request: Request, limit: int = Query(20, ge=1, le=50)):
    ctx = await _ctx(request)
    reports = await report_service.list_reports(ctx["business_id"])
    return {"success": True, "reports": reports[:limit]}


@router.post("/api/admin/analytics/reports")
async def create_report(request: Request):
    ctx = await _ctx(request)
    if "report:gen" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无报告权限"})
    body = await request.json()
    created = await report_service.generate_report(
        ctx["business_id"], ctx["staff"], body.get("timeWindow") or None
    )
    return {"success": True, **created}


@router.post("/api/admin/analytics/reports/from-result")
async def save_result_report(request: Request):
    """对话结果卡 → 存为报告(我的报告页可见、可导 CSV;权限同报告生成)。

    只搬运对话里真实执行过的查询结果(14-D3:不重算、不编造),行数上限 200。
    """
    ctx = await _ctx(request)
    if "report:gen" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无报告权限"})
    body = await request.json()
    rows = body.get("rows")
    if not isinstance(rows, list):
        return JSONResponse(status_code=400, content={"success": False, "message": "rows 必传(list)"})
    created = await report_service.save_result_report(
        ctx["business_id"], ctx["staff"], str(body.get("question") or ""),
        str(body.get("metric") or "result"), str(body.get("unit") or ""),
        str(body.get("caliber") or ""), rows[:200],
        chart=(str(body.get("chart")) if body.get("chart") else None),
    )
    return {"success": True, **created}


@router.get("/api/admin/analytics/reports/{report_id}")
async def get_report(request: Request, report_id: str):
    ctx = await _ctx(request)
    report = await report_service.get_report(ctx["business_id"], report_id)
    if not report:
        return JSONResponse(status_code=404, content={"success": False, "message": "报告不存在"})
    return {"success": True, **report}


@router.get("/api/admin/analytics/reports/{report_id}/csv")
async def export_report_csv(request: Request, report_id: str):
    ctx = await _ctx(request)
    if "report:csv" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无报告导出权限"})
    csv_text = await report_service.export_csv(ctx["business_id"], report_id)
    if csv_text is None:
        return JSONResponse(status_code=404, content={"success": False, "message": "报告不存在"})
    return JSONResponse(
        content={"success": True, "filename": f"{report_id}.csv", "csv": csv_text},
    )


# ---------------- 优惠活动(20 号;写操作限老板/运营) ----------------


@router.get("/api/admin/analytics/promotions")
async def promotions_list(request: Request):
    await _ctx(request)  # 鉴权闸(租户上下文缺失即 403);列表本身跨租户只读汇总
    return {"success": True, "promotions": await promotions.list_promotions(), "effect": await promotions.effect_overview()}


@router.post("/api/admin/analytics/promotions")
async def promotions_create(request: Request):
    ctx = await _ctx(request)
    if "promo:create" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无优惠活动编辑权限"})
    body = await request.json()
    result = await promotions.create_promotion(body, ctx["staff"])
    if "error" in result:
        return JSONResponse(status_code=400, content={"success": False, **result})
    return {"success": True, **result}


@router.post("/api/admin/analytics/promotions/{promotion_id}/status")
async def promotions_set_status(promotion_id: str, request: Request):
    ctx = await _ctx(request)
    if "promo:disable" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无优惠活动编辑权限"})
    body = await request.json()
    result = await promotions.set_promotion_status(promotion_id, str(body.get("status") or ""), ctx["staff"])
    if "error" in result:
        return JSONResponse(status_code=400, content={"success": False, **result})
    return {"success": True, **result}


# ---------------- 菜单管理 CRUD(13 号;系统菜单护栏在服务层) ----------------


@router.post("/api/admin/analytics/menus")
async def create_menu(request: Request):
    ctx = await _ctx(request)
    if not rbac.is_manager(ctx["role"]):
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板/管理员可管理菜单"})
    body = await request.json()
    name = str(body.get("name") or "").strip()
    menu_type = body.get("menuType") or "menu"
    if not name or menu_type not in ("directory", "menu", "button"):
        return JSONResponse(status_code=400, content={"success": False, "message": "name/menuType 必传;类型 ∈ directory|menu|button"})
    import uuid as _uuid

    from engine_py.db import Menu, RoleMenu, get_session

    menu_id = "m_" + _uuid.uuid4().hex[:10]
    async with get_session() as session:
        session.add(Menu(
            id=menu_id, business_id=ctx["business_id"], parent_id=body.get("parentId"),
            name=name, menu_type=menu_type, route=body.get("route") or None,
            perm_code=body.get("permCode") or None, sort_order=int(body.get("sort") or 0),
            status="enabled",
        ))
        # 建成即对管理角色可见(否则新菜单不在任何 role_menus 里,谁都看不到)
        for manager_role in rbac.MANAGER_ROLES:
            session.add(RoleMenu(role=manager_role, menu_id=menu_id, business_id=ctx["business_id"]))
        await session.commit()
    return {"success": True, "id": menu_id}


@router.patch("/api/admin/analytics/menus/{menu_id}")
async def update_menu(menu_id: str, request: Request):
    ctx = await _ctx(request)
    if not rbac.is_manager(ctx["role"]):
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板/管理员可管理菜单"})
    body = await request.json()
    from engine_py.db import Menu, get_session
    from sqlalchemy import select

    async with get_session() as session:
        row = (
            await session.execute(
                select(Menu).where(Menu.id == menu_id, Menu.business_id == ctx["business_id"])
            )
        ).scalars().first()
        if not row:
            return JSONResponse(status_code=404, content={"success": False, "message": "菜单不存在"})
        if menu_id in rbac.SYSTEM_MENU_IDS and body.get("status") == "disabled":
            return JSONResponse(status_code=400, content={"success": False, "message": "护栏:系统菜单不可停用"})
        for field in ("name", "route", "permCode", "sort", "status"):
            if field in body:
                setattr(row, {"permCode": "perm_code", "sort": "sort_order"}.get(field, field), body[field])
        await session.commit()
    return {"success": True, "id": menu_id}


@router.delete("/api/admin/analytics/menus/{menu_id}")
async def delete_menu(menu_id: str, request: Request):
    ctx = await _ctx(request)
    if not rbac.is_manager(ctx["role"]):
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板/管理员可管理菜单"})
    if menu_id in rbac.SYSTEM_MENU_IDS:
        return JSONResponse(status_code=400, content={"success": False, "message": "护栏:系统菜单不可删除"})
    from engine_py.db import Menu, RoleMenu, get_session
    from sqlalchemy import select

    async with get_session() as session:
        children = (
            await session.execute(
                select(Menu).where(Menu.parent_id == menu_id, Menu.business_id == ctx["business_id"])
            )
        ).scalars().first()
        if children:
            return JSONResponse(status_code=400, content={"success": False, "message": "存在子菜单,先删子项"})
        await session.execute(
            delete(RoleMenu).where(RoleMenu.menu_id == menu_id, RoleMenu.business_id == ctx["business_id"])
        )
        row = (
            await session.execute(
                select(Menu).where(Menu.id == menu_id, Menu.business_id == ctx["business_id"])
            )
        ).scalars().first()
        if row:
            await session.delete(row)
        await session.commit()
    return {"success": True}


# ---------------- 角色管理(列表/新建) ----------------


@router.get("/api/admin/analytics/roles")
async def roles_list(request: Request):
    """角色列表(0013 后无「内置」特权:三档种子只是预置配置,可像自定义角色
    一样重新分配;仅老板角色保留系统菜单防锁死护栏)。"""
    from engine_py.db import RoleMenu, StaffMember, get_session
    from sqlalchemy import func, select

    ctx = await _ctx(request)
    async with get_session() as session:
        menu_counts = dict(
            (await session.execute(
                select(RoleMenu.role, func.count())
                .where(RoleMenu.business_id == ctx["business_id"])
                .group_by(RoleMenu.role)
            )).all()
        )
        staff_counts = dict(
            (await session.execute(
                select(StaffMember.role, func.count())
                .where(StaffMember.business_id == ctx["business_id"])
                .group_by(StaffMember.role)
            )).all()
        )
    role_names = {*rbac.ROLES, *menu_counts, *staff_counts}
    return {"success": True, "roles": [
        {"role": role, "menuCount": menu_counts.get(role, 0), "staffCount": staff_counts.get(role, 0)}
        for role in sorted(role_names)
    ]}


@router.post("/api/admin/analytics/roles")
async def roles_create(request: Request):
    ctx = await _ctx(request)
    if not rbac.is_manager(ctx["role"]):
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板/管理员可新建角色"})
    body = await request.json()
    role = str(body.get("role") or "").strip()
    menu_ids = list(body.get("menuIds") or [])
    if not role or " " in role:
        return JSONResponse(status_code=400, content={"success": False, "message": "role 必传且不含空格"})
    if not menu_ids:
        return JSONResponse(status_code=400, content={"success": False, "message": "至少分配一个菜单"})
    from engine_py.db import RoleMenu, get_session

    async with get_session() as session:
        exists = (
            await session.execute(
                select(RoleMenu).where(RoleMenu.role == role, RoleMenu.business_id == ctx["business_id"])
            )
        ).scalars().first()
    if exists:
        return JSONResponse(status_code=400, content={"success": False, "message": f"角色 {role} 已存在,请在列表中直接调整其权限"})
    await rbac.set_role_menus(ctx["business_id"], role, menu_ids, ctx["staff"])
    return {"success": True, "role": role, "menuCount": len(menu_ids)}


# ---------------- 员工管理(邀请/改角色/停用) ----------------


@router.post("/api/admin/analytics/staff")
async def staff_invite(request: Request):
    ctx = await _ctx(request)
    if not rbac.is_manager(ctx["role"]):
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板/管理员可邀请员工"})
    body = await request.json()
    email = str(body.get("email") or "").strip().lower()
    display = str(body.get("displayName") or email).strip()
    role = body.get("role") or "sales_viewer"
    if not email or "@" not in email:
        return JSONResponse(status_code=400, content={"success": False, "message": "email 必传"})
    if role not in (*rbac.ROLES,) and not role.startswith("custom_"):
        role = f"custom_{role}"
    import uuid as _uuid

    from engine_py.db import StaffMember, get_session

    async with get_session() as session:
        exists = (
            await session.execute(
                select(StaffMember).where(StaffMember.business_id == ctx["business_id"], StaffMember.email == email)
            )
        ).scalars().first()
        if exists:
            return JSONResponse(status_code=400, content={"success": False, "message": "该邮箱已存在"})
        row = StaffMember(
            id=f"staff_{_uuid.uuid4().hex[:10]}", business_id=ctx["business_id"],
            email=email, display_name=display, role=role, status="enabled",
            password_hash=rbac.seed_password_hash(),  # 0013:新员工以种子密码可真实登录
        )
        session.add(row)
        await session.commit()
        return {"success": True, "id": row.id, "email": email, "role": role}


@router.patch("/api/admin/analytics/staff/{staff_id}")
async def staff_update(staff_id: str, request: Request):
    ctx = await _ctx(request)
    if not rbac.is_manager(ctx["role"]):
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板/管理员可管理员工"})
    body = await request.json()
    from engine_py.db import StaffMember, get_session
    from sqlalchemy import select

    async with get_session() as session:
        row = (
            await session.execute(
                select(StaffMember).where(StaffMember.business_id == ctx["business_id"], StaffMember.id == staff_id)
            )
        ).scalars().first()
        if not row:
            return JSONResponse(status_code=404, content={"success": False, "message": "员工不存在"})
        if row.role == "finance_owner" and body.get("status") == "disabled":
            return JSONResponse(status_code=400, content={"success": False, "message": "护栏:老板账号不可停用"})
        if row.role == "finance_owner" and "role" in body:
            return JSONResponse(status_code=400, content={"success": False, "message": "护栏:老板角色不可降级(防锁死)"})
        if "role" in body:
            row.role = body["role"]
        if "status" in body:
            row.status = body["status"]
        if "displayName" in body:
            row.display_name = body["displayName"]
        await session.commit()
        return {"success": True, "id": row.id, "role": row.role, "status": row.status}


# ---------------- 客户管理(列表 + 会员级编辑;数据来自商户库) ----------------


@router.get("/api/admin/analytics/customers")
async def customers_list(request: Request):
    await _ctx(request)
    from engine_py.tools_registry.order_domain import _merchant_reader_engine
    from sqlalchemy import text as _text

    async with _merchant_reader_engine().connect() as conn:
        rows = (
            await conn.execute(_text(
                "SELECT c.customer_id, c.name, c.phone, COALESCE(c.email, '') AS email, "
                "COALESCE(c.member_level, 'VIP') AS member_level, "
                "COALESCE(c.addresses, '[]'::jsonb)::text AS addresses, "
                "COALESCE(SUM(o.total_amount), 0)::float AS total_spent, COUNT(o.order_id) AS order_count "
                "FROM merchant_customers c "
                "LEFT JOIN merchant_orders o ON o.customer_id = c.customer_id "
                "GROUP BY c.customer_id, c.name, c.phone, c.email, c.member_level, c.addresses "
                "ORDER BY total_spent DESC LIMIT 100"
            ))
        ).mappings().all()
    return {"success": True, "customers": [dict(r) for r in rows]}


@router.get("/api/admin/analytics/customers/{customer_id}/coupons")
async def customer_coupons(customer_id: str, request: Request):
    """客户关联优惠券(user_id 与商户客户档案同源;含已使用)。"""
    await _ctx(request)
    from engine_py.tools_registry.order_domain import _merchant_reader_engine
    from sqlalchemy import text as _text

    async with _merchant_reader_engine().connect() as conn:
        rows = (
            await conn.execute(_text(
                "SELECT uc.id::text AS id, p.name, p.discount_value::float AS value, uc.status, "
                "uc.claimed_at, uc.used_order_id "
                "FROM user_coupons uc JOIN promotions p ON p.id = uc.promotion_id "
                "WHERE uc.user_id = :cid ORDER BY uc.claimed_at DESC LIMIT 50"
            ).bindparams(cid=customer_id))
        ).mappings().all()
    return {"success": True, "coupons": [
        {
            "id": r["id"], "name": r["name"], "value": r["value"], "status": r["status"],
            "claimedAt": r["claimed_at"].isoformat() if r["claimed_at"] else None,
            "usedOrderId": r["used_order_id"],
        } for r in rows
    ]}


@router.patch("/api/admin/analytics/customers/{customer_id}")
async def customer_update(customer_id: str, request: Request):
    ctx = await _ctx(request)
    if ctx["role"] != "finance_owner":
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板可编辑客户"})
    body = await request.json()
    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _text

    async with _merchant_writer_engine().begin() as conn:
        result = await conn.execute(
            _text("UPDATE merchant_customers SET member_level = :lv, updated_at = NOW() WHERE customer_id = :cid")
            .bindparams(lv=str(body.get("memberLevel") or "VIP"), cid=customer_id)
        )
        if result.rowcount == 0:
            return JSONResponse(status_code=404, content={"success": False, "message": "客户不存在"})
    return {"success": True, "customerId": customer_id, "memberLevel": body.get("memberLevel")}


# ---------------- 优惠核销(订单↔优惠关联;20-D4) ----------------


@router.post("/api/admin/analytics/promotions/{promotion_id}/redeem")
async def promotions_redeem(promotion_id: str, request: Request):
    ctx = await _ctx(request)
    if "promo:redeem" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无核销权限"})
    body = await request.json()
    order_id = str(body.get("orderId") or "").strip()
    if not order_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "orderId 必传"})
    result = await promotions.redeem(promotion_id, order_id, ctx["staff"])
    if "error" in result:
        return JSONResponse(status_code=400, content={"success": False, **result})
    return {"success": True, **result}


@router.post("/api/admin/analytics/promotions/{promotion_id}/grant")
async def promotions_grant(promotion_id: str, request: Request):
    """商家向指定客户发券(复用领券护栏:仅券型/在售/同人同活动一次)。"""
    ctx = await _ctx(request)
    if "promo:create" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无发券权限"})
    body = await request.json()
    customer_id = str(body.get("customerId") or "").strip()
    if not customer_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "customerId 必传"})
    result = await promotions.claim_coupon(promotion_id, customer_id)
    if "error" in result:
        return JSONResponse(status_code=400, content={"success": False, **result})
    return {"success": True, **result}


# ---------------- SPU/SKU 增删改查(商品目录直写;删除受订单引用护栏) ----------------


def _spu_cols():
    return ("SELECT s.id::text AS id, s.spu_code, s.title, s.category, s.status, "
            "COALESCE(MIN(k.price), 0)::float AS price, COALESCE(SUM(k.stock), 0)::int AS stock "
            "FROM merchant_spus s LEFT JOIN merchant_skus k ON k.spu_id = s.id ")


@router.get("/api/admin/analytics/spus")
async def spus_list(request: Request):
    await _ctx(request)
    from engine_py.tools_registry.order_domain import _merchant_reader_engine
    from sqlalchemy import text as _t

    async with _merchant_reader_engine().connect() as conn:
        rows = (await conn.execute(_t(
            _spu_cols() + "GROUP BY s.id, s.spu_code, s.title, s.category, s.status ORDER BY s.title LIMIT 200"
        ))).mappings().all()
    return {"success": True, "spus": [dict(r) for r in rows]}


@router.post("/api/admin/analytics/spus")
async def spus_create(request: Request):
    ctx = await _ctx(request)
    if "prod:edit" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无商品编辑权限"})
    body = await request.json()
    title = str(body.get("title") or "").strip()
    category = str(body.get("category") or "").strip()
    price = body.get("price")
    stock = int(body.get("stock") or 0)
    if not title or not category or price is None:
        return JSONResponse(status_code=400, content={"success": False, "message": "title/category/price 必传"})
    import uuid as _u

    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    spu_id = str(_u.uuid4())
    code = f"SPU-{_u.uuid4().hex[:8].upper()}"
    async with _merchant_writer_engine().begin() as conn:
        # asyncpg 严格类型:varchar 入 uuid 列必须显式 CAST(update/delete 同款写法);
        # main_image/sku_title/spec_attributes 为 NOT NULL,新建时落诚实默认值
        await conn.execute(_t(
            "INSERT INTO merchant_spus (id, spu_code, title, category, main_image, status) "
            "VALUES (CAST(:id AS uuid), :code, :t, :cat, '', 'ON_SALE')"
        ).bindparams(id=spu_id, code=code, t=title, cat=category))
        await conn.execute(_t(
            "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, spec_attributes, price, stock) "
            "VALUES (CAST(:id AS uuid), CAST(:spu AS uuid), :code, :st, CAST(:attrs AS jsonb), :price, :stock)"
        ).bindparams(id=str(_u.uuid4()), spu=spu_id, code=code + "-SKU-1",
                     st=f"{title} 默认款", attrs="{}", price=float(price), stock=stock))
    return {"success": True, "id": spu_id, "spuCode": code}


@router.patch("/api/admin/analytics/spus/{spu_id}")
async def spus_update(spu_id: str, request: Request):
    ctx = await _ctx(request)
    if "prod:edit" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无商品编辑权限"})
    body = await request.json()
    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    async with _merchant_writer_engine().begin() as conn:
        if "status" in body:
            if body["status"] not in ("ON_SALE", "OFF_SALE"):
                return JSONResponse(status_code=400, content={"success": False, "message": "status ∈ ON_SALE|OFF_SALE"})
            await conn.execute(_t("UPDATE merchant_spus SET status = :s WHERE id = CAST(:id AS uuid)")
                               .bindparams(s=body["status"], id=spu_id))
        if "title" in body:
            await conn.execute(_t("UPDATE merchant_spus SET title = :t WHERE id = CAST(:id AS uuid)")
                               .bindparams(t=str(body["title"]), id=spu_id))
        if "price" in body:
            await conn.execute(_t(
                "UPDATE merchant_skus SET price = :p WHERE id = (SELECT id FROM merchant_skus WHERE spu_id = CAST(:id AS uuid) LIMIT 1)"
            ).bindparams(p=float(body["price"]), id=spu_id))
        if "stock" in body:
            await conn.execute(_t(
                "UPDATE merchant_skus SET stock = :s WHERE id = (SELECT id FROM merchant_skus WHERE spu_id = CAST(:id AS uuid) LIMIT 1)"
            ).bindparams(s=int(body["stock"]), id=spu_id))
    return {"success": True, "id": spu_id}


@router.delete("/api/admin/analytics/spus/{spu_id}")
async def spus_delete(spu_id: str, request: Request):
    ctx = await _ctx(request)
    if "prod:edit" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无商品编辑权限"})
    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    async with _merchant_writer_engine().begin() as conn:
        code = (await conn.execute(_t("SELECT spu_code FROM merchant_spus WHERE id = CAST(:id AS uuid)")
                                  .bindparams(id=spu_id))).scalar()
        if not code:
            return JSONResponse(status_code=404, content={"success": False, "message": "商品不存在"})
        referenced = (await conn.execute(_t(
            "SELECT 1 FROM merchant_order_items WHERE spu_id = :c LIMIT 1").bindparams(c=code))).first()
        if referenced:
            return JSONResponse(status_code=400, content={
                "success": False,
                "message": "该商品已有成交记录,不可删除(可下架 OFF_SALE)",
            })
        await conn.execute(_t("DELETE FROM merchant_skus WHERE spu_id = CAST(:id AS uuid)").bindparams(id=spu_id))
        await conn.execute(_t("DELETE FROM merchant_spus WHERE id = CAST(:id AS uuid)").bindparams(id=spu_id))
    return {"success": True}


# ---------------- 优惠活动 编辑/删除(20 号补齐增删改查) ----------------


@router.patch("/api/admin/analytics/promotions/{promotion_id}")
async def promotions_update(promotion_id: str, request: Request):
    ctx = await _ctx(request)
    if "promo:create" not in ctx["perms"]:  # 编辑随建/改活动权限点(0013 动态化)
        return JSONResponse(status_code=403, content={"success": False, "message": "无优惠活动编辑权限"})
    body = await request.json()
    from engine_py.analytics import promotions as P
    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    sets, params = [], {"id": promotion_id}
    if "name" in body:
        sets.append("name = :name"); params["name"] = str(body["name"])
    if "value" in body:
        sets.append("discount_value = :v"); params["v"] = float(body["value"])
    if "threshold" in body:
        sets.append("threshold_amount = :th"); params["th"] = body["threshold"]
    async with _merchant_writer_engine().begin() as conn:
        if not sets:
            return JSONResponse(status_code=400, content={"success": False, "message": "无可更新字段"})
        await conn.execute(_t(f"UPDATE promotions SET {', '.join(sets)} WHERE id = CAST(:id AS uuid)").bindparams(**params))
    await P._audit("promo_update", ctx["staff"], {"id": promotion_id, **body})
    return {"success": True, "id": promotion_id}


@router.delete("/api/admin/analytics/promotions/{promotion_id}")
async def promotions_delete(promotion_id: str, request: Request):
    ctx = await _ctx(request)
    if ctx["role"] != "finance_owner":
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板可删除活动"})
    from engine_py.analytics import promotions as P
    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    async with _merchant_writer_engine().begin() as conn:
        used = (await conn.execute(_t(
            "SELECT 1 FROM promotion_redemptions WHERE promotion_id = CAST(:id AS uuid) LIMIT 1"
        ).bindparams(id=promotion_id))).first()
        if used:
            return JSONResponse(status_code=400, content={"success": False, "message": "已有核销记录,只可停用不可删除"})
        await conn.execute(_t("DELETE FROM promotions WHERE id = CAST(:id AS uuid)").bindparams(id=promotion_id))
    await P._audit("promo_delete", ctx["staff"], {"id": promotion_id})
    return {"success": True}


# ---------------- 客户 新增/删除(20 号补齐) ----------------


@router.post("/api/admin/analytics/customers")
async def customers_create(request: Request):
    ctx = await _ctx(request)
    if ctx["role"] != "finance_owner":
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板可新增客户"})
    body = await request.json()
    name = str(body.get("name") or "").strip()
    phone = str(body.get("phone") or "").strip()
    if not name or not phone:
        return JSONResponse(status_code=400, content={"success": False, "message": "name/phone 必传"})
    import uuid as _u

    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    cid = f"CUST-{_u.uuid4().hex[:8].upper()}"
    async with _merchant_writer_engine().begin() as conn:
        await conn.execute(_t(
            "INSERT INTO merchant_customers (customer_id, name, phone, member_level) "
            "VALUES (:cid, :n, :p, :lv)"
        ).bindparams(cid=cid, n=name, p=phone, lv=body.get("memberLevel") or "VIP"))
    return {"success": True, "customerId": cid}


@router.delete("/api/admin/analytics/customers/{customer_id}")
async def customers_delete(customer_id: str, request: Request):
    ctx = await _ctx(request)
    if ctx["role"] != "finance_owner":
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板可删除客户"})
    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    async with _merchant_writer_engine().begin() as conn:
        has_orders = (await conn.execute(_t(
            "SELECT 1 FROM merchant_orders WHERE customer_id = :c LIMIT 1").bindparams(c=customer_id))).first()
        if has_orders:
            return JSONResponse(status_code=400, content={"success": False, "message": "客户名下有订单,不可删除"})
        await conn.execute(_t("DELETE FROM merchant_customers WHERE customer_id = :c").bindparams(c=customer_id))
    return {"success": True}


# ---------------- SKU 明细增删改查(承接 SPU 页展开) ----------------


@router.get("/api/admin/analytics/skus")
async def skus_stock_list(request: Request):
    """跨 SPU 的 SKU 库存总表(SKU 库存菜单独立视角;行内改价/改库存走
    既有 PATCH /skus/{id};低库存阈值口径与工作台一致,前端过滤)。"""
    await _ctx(request)
    from engine_py.tools_registry.order_domain import _merchant_reader_engine
    from sqlalchemy import text as _t

    async with _merchant_reader_engine().connect() as conn:
        rows = (await conn.execute(_t(
            "SELECT k.id::text AS id, k.sku_code, k.sku_title, s.id::text AS spu_id, "
            "s.title AS spu_title, k.price::float AS price, k.stock, "
            "k.spec_attributes::text AS spec_attributes "
            "FROM merchant_skus k JOIN merchant_spus s ON s.id = k.spu_id "
            "ORDER BY k.sku_code LIMIT 500"
        ))).mappings().all()
    return {"success": True, "skus": [dict(r) for r in rows]}


@router.get("/api/admin/analytics/spus/{spu_id}/skus")
async def skus_list(spu_id: str, request: Request):
    await _ctx(request)
    from engine_py.tools_registry.order_domain import _merchant_reader_engine
    from sqlalchemy import text as _t

    async with _merchant_reader_engine().connect() as conn:
        rows = (await conn.execute(_t(
            "SELECT id::text, sku_code, sku_title, price::float AS price, stock, "
            "spec_attributes::text AS spec_attributes FROM merchant_skus "
            "WHERE spu_id = CAST(:id AS uuid) ORDER BY sku_code"
        ).bindparams(id=spu_id))).mappings().all()
    return {"success": True, "skus": [dict(r) for r in rows]}


@router.post("/api/admin/analytics/spus/{spu_id}/skus")
async def skus_create(spu_id: str, request: Request):
    ctx = await _ctx(request)
    if "prod:edit" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无商品编辑权限"})
    body = await request.json()
    price = body.get("price")
    if price is None:
        return JSONResponse(status_code=400, content={"success": False, "message": "price 必传"})
    import uuid as _u

    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    sku_code = f"SKU-{_u.uuid4().hex[:10].upper()}"
    spec = body.get("specAttributes") or {}
    async with _merchant_writer_engine().begin() as conn:
        spu = (await conn.execute(_t("SELECT spu_code FROM merchant_spus WHERE id = CAST(:id AS uuid)")
                                  .bindparams(id=spu_id))).first()
        if not spu:
            return JSONResponse(status_code=404, content={"success": False, "message": "SPU 不存在"})
        await conn.execute(_t(
            "INSERT INTO merchant_skus (id, spu_id, sku_code, sku_title, price, stock, spec_attributes) "
            "VALUES (:id, CAST(:spu AS uuid), :code, :title, :price, :stock, CAST(:spec AS jsonb))"
        ).bindparams(id=str(_u.uuid4()), spu=spu_id, code=sku_code,
                     title=body.get("skuTitle") or "", price=float(price),
                     stock=int(body.get("stock") or 0), spec=_u.json.dumps(spec, ensure_ascii=False)))
    return {"success": True, "skuCode": sku_code}


@router.patch("/api/admin/analytics/skus/{sku_id}")
async def skus_update(sku_id: str, request: Request):
    ctx = await _ctx(request)
    if "prod:edit" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无商品编辑权限"})
    body = await request.json()
    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    sets, params = [], {"id": sku_id}
    for field, col in (("price", "price"), ("stock", "stock")):
        if field in body:
            sets.append(f"{col} = :{field}")
            params[field] = float(body[field]) if field == "price" else int(body[field])
    if "skuTitle" in body:
        sets.append("sku_title = :skuTitle")
        params["skuTitle"] = str(body["skuTitle"])
    if not sets:
        return JSONResponse(status_code=400, content={"success": False, "message": "无可更新字段"})
    async with _merchant_writer_engine().begin() as conn:
        await conn.execute(_t(f"UPDATE merchant_skus SET {', '.join(sets)} WHERE id = CAST(:id AS uuid)").bindparams(**params))
    return {"success": True, "id": sku_id}


@router.delete("/api/admin/analytics/skus/{sku_id}")
async def skus_delete(sku_id: str, request: Request):
    ctx = await _ctx(request)
    if "prod:edit" not in ctx["perms"]:
        return JSONResponse(status_code=403, content={"success": False, "message": "无商品编辑权限"})
    from engine_py.tools_registry.order_domain import _merchant_writer_engine
    from sqlalchemy import text as _t

    async with _merchant_writer_engine().begin() as conn:
        sold = (await conn.execute(_t(
            "SELECT 1 FROM merchant_order_items WHERE sku_code = "
            "(SELECT sku_code FROM merchant_skus WHERE id = CAST(:id AS uuid)) LIMIT 1"
        ).bindparams(id=sku_id))).first()
        if sold:
            return JSONResponse(status_code=400, content={"success": False, "message": "该 SKU 已有成交,不可删除(可改库存为 0)"})
        await conn.execute(_t("DELETE FROM merchant_skus WHERE id = CAST(:id AS uuid)").bindparams(id=sku_id))
    return {"success": True}
