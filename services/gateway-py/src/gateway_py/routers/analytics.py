"""商户 data agent 路由组(09-D2;/api/admin/analytics/*)。

员工鉴权面(与 /api/admin/* 同域:身份经 x-user-id/x-tenant-id 头,复用
require_tenant_context 语义);轻管线直调 engine(analytics 包),不走
Temporal(15 号决议)。SSE 帧:event: clarify|result|unsupported|error。
"""

from __future__ import annotations

import asyncio
import json

from engine_py.analytics import graph, promotions, rbac, report_service
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from gateway_py.tenant_context import require_tenant_context

router = APIRouter(tags=["merchant-analytics"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _ctx(request: Request) -> dict:
    tc = require_tenant_context()
    staff = request.headers.get("x-user-id") or "staff_owner"
    role, display = await rbac.resolve_staff_role(tc.get("tenantId") or "aurora", staff)
    return {"business_id": tc.get("tenantId") or "aurora", "role": role, "staff": staff, "display": display}


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
            outcome = await graph.ask(question, ctx, body.get("pageContext"))
        except Exception as err:
            outcome = {"type": "error", "message": str(err)}
        yield _sse(outcome.get("type", "error"), outcome)
        await asyncio.sleep(0)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
    })


@router.get("/api/admin/analytics/menus")
async def analytics_menus(request: Request):
    ctx = await _ctx(request)
    await rbac.ensure_defaults(ctx["business_id"])
    tree = await rbac.menu_tree_for_role(ctx["business_id"], ctx["role"])
    return {"success": True, "role": ctx["role"], "menus": tree}


@router.post("/api/admin/analytics/roles/{role}/menus")
async def set_role_menus(role: str, request: Request):
    """保存角色菜单分配(保存即生效 + 审计口子留给 merchant_audit_logs 接线)。"""
    ctx = await _ctx(request)
    if role not in rbac.ROLES:
        return JSONResponse(status_code=400, content={"success": False, "message": f"未知角色 {role}"})
    if ctx["role"] != "finance_owner":
        return JSONResponse(status_code=403, content={"success": False, "message": "仅老板可分配权限"})
    body = await request.json()
    await rbac.set_role_menus(ctx["business_id"], role, list(body.get("menuIds") or []), ctx["staff"])
    return {"success": True}


@router.get("/api/admin/analytics/staff")
async def analytics_staff(request: Request):
    from engine_py.db import StaffMember, get_session
    from sqlalchemy import select

    ctx = await _ctx(request)
    await rbac.ensure_defaults(ctx["business_id"])
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
    """快捷切换账号(13 号):切换 = 重新解析身份(头更新由前端承担),此处
    返回目标员工画像 + 角色可见菜单,审计口子留给接线。"""
    body = await request.json()
    target = str(body.get("staffId") or "").strip()
    if not target:
        return JSONResponse(status_code=400, content={"success": False, "message": "staffId 必传"})
    tc = require_tenant_context()
    business_id = tc.get("tenantId") or "aurora"
    role, display = await rbac.resolve_staff_role(business_id, target)
    tree = await rbac.menu_tree_for_role(business_id, role)
    return {"success": True, "staffId": target, "displayName": display, "role": role, "menus": tree}


@router.get("/api/admin/analytics/reports")
async def analytics_reports(request: Request, limit: int = Query(20, ge=1, le=50)):
    ctx = await _ctx(request)
    reports = await report_service.list_reports(ctx["business_id"])
    return {"success": True, "reports": reports[:limit]}


@router.post("/api/admin/analytics/reports")
async def create_report(request: Request):
    ctx = await _ctx(request)
    if ctx["role"] not in ("finance_owner", "sales_viewer"):
        return JSONResponse(status_code=403, content={"success": False, "message": "无报告权限"})
    body = await request.json()
    created = await report_service.generate_report(
        ctx["business_id"], ctx["staff"], body.get("timeWindow") or None
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
    if ctx["role"] not in ("finance_owner", "sales_viewer"):
        return JSONResponse(status_code=403, content={"success": False, "message": "无优惠活动编辑权限"})
    body = await request.json()
    result = await promotions.create_promotion(body, ctx["staff"])
    if "error" in result:
        return JSONResponse(status_code=400, content={"success": False, **result})
    return {"success": True, **result}


@router.post("/api/admin/analytics/promotions/{promotion_id}/status")
async def promotions_set_status(promotion_id: str, request: Request):
    ctx = await _ctx(request)
    if ctx["role"] not in ("finance_owner", "sales_viewer"):
        return JSONResponse(status_code=403, content={"success": False, "message": "无优惠活动编辑权限"})
    body = await request.json()
    result = await promotions.set_promotion_status(promotion_id, str(body.get("status") or ""), ctx["staff"])
    if "error" in result:
        return JSONResponse(status_code=400, content={"success": False, **result})
    return {"success": True, **result}
