"""坐席台独立页路由(live-desk-rework P2;冻结面外新增,同批 pytest 契约钉死)。

P2 范围:坐席在线态读(presence)+ 免打扰自拨;P3 将扩 `/threads/{id}/context`
聚合端点。鉴权统一 Bearer JWT → 在职员工(0013 身份模型,租户由员工行带出,
不收客户端租户参数);按钮闸 `live_desk:operate` 照 order:ship 的
perms_for_role 先例(角色管理页勾选即生效)。
"""

from __future__ import annotations

from engine_py.analytics import rbac
from engine_py.approvals import presence
from engine_py.db import StaffMember, get_session
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
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
