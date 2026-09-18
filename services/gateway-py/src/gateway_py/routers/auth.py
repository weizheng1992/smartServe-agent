"""Auth 路由 — /api/auth/login|logout|me(web 真实登录链路)。

新增于 39 条冻结路由之外(冻结契约只约束既有路由形状);本组契约由
tests/test_http_routes_contract.py 的 auth 用例钉死。

- 凭证:staff_members.password_hash(员工,0013)优先,回落 users.password_hash
  (平台账号;seed 以 E2E_ACCOUNT_PASSWORD 覆写种子账号)。
- 会话:JWT HS256 长过期(默认 30 天,无刷新),claims 携带 sub/email/jti。
- 登出:Redis jti 黑名单(TTL 截止 token 自然过期),``/api/auth/me`` 拒绝已登出 token。
- 邮箱不存在与密码错误统一 401 文案(防账号枚举),并对未知邮箱做等时 dummy 校验。
- 成功载荷走统一信封 ``{success, data: {user, token}}``(server-gateway §1.4)。
- require_claims / issue_token 同时供 analytics 组做员工身份收口(0013:
  /api/admin/analytics/* 不再信任 x-user-id 头)。
"""

from __future__ import annotations

import datetime as _dt
import functools
import logging
import os
import uuid

import bcrypt
import jwt
from engine_py.db import StaffMember, User, get_session
from engine_py.event_bus import get_client as get_redis
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

router = APIRouter()

# 生产必须显式注入 AUTH_JWT_SECRET;缺省值仅供本地/E2E(与 seed 的缺省密码同一约束级别),
# 长度 ≥32 字节以满足 HS256 推荐密钥长度。使用缺省密钥时显式告警,不让"生产忘配"静默通过。
_JWT_DEV_SECRET = "dev-only-insecure-jwt-secret-pad-to-32-bytes"
if "AUTH_JWT_SECRET" not in os.environ:
    logging.getLogger(__name__).warning(
        "AUTH_JWT_SECRET 未注入,正在使用开发缺省密钥签发 JWT —— 生产环境必须显式配置"
    )
_JWT_SECRET = os.environ.get("AUTH_JWT_SECRET", _JWT_DEV_SECRET)
_TTL_DAYS = int(os.environ.get("AUTH_TOKEN_TTL_DAYS", "30"))
_DENY_PREFIX = "auth:denylist:"


class LoginIn(BaseModel):
    email: str
    password: str


class RegisterIn(BaseModel):
    email: str
    password: str
    displayName: str = ""


@functools.lru_cache(maxsize=1)
def _dummy_hash() -> bytes:
    """等时防枚举:邮箱不存在时也走一次 bcrypt 校验,抹平响应时间差。"""
    return bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt())


def _unauthorized(message: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"success": False, "error": message})


def issue_token(subject: str, email: str) -> str:
    """签发员工/用户 JWT(0013:staff/switch 复用,切换身份 = 换签 token)。"""
    now = _dt.datetime.now(tz=_dt.UTC)
    claims = {
        "sub": str(subject),
        "email": email,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + _dt.timedelta(days=_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(claims, _JWT_SECRET, algorithm="HS256")


async def require_claims(authorization: str | None) -> dict:
    """校验 Bearer JWT;坏 token / 黑名单 token → 401(供其他路由组复用)。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer 凭证")
    try:
        claims = jwt.decode(authorization.removeprefix("Bearer "), _JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="凭证无效或已过期") from None
    if await (await get_redis()).get(_DENY_PREFIX + claims.get("jti", "")):
        raise HTTPException(status_code=401, detail="凭证已登出")
    return claims


async def _resolve_bearer(authorization: str | None) -> dict | JSONResponse:
    """校验 Bearer JWT;坏 token / 黑名单 token → 401 响应,否则返回 claims。"""
    try:
        return await require_claims(authorization)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(exc.detail)})


@router.post("/api/auth/login")
async def login(body: LoginIn):
    async with get_session() as session:
        staff = (
            await session.execute(
                select(StaffMember).where(StaffMember.email == body.email, StaffMember.status == "enabled")
            )
        ).scalars().first()
        user = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()

    # 员工凭证优先(0013);员工无密码则回落平台账号,均无 → 等时 dummy 后 401
    stored_hash: str | None = None
    subject = ""
    if staff is not None and staff.password_hash:
        stored_hash, subject = staff.password_hash, staff.id
    elif user is not None and user.password_hash:
        stored_hash, subject = user.password_hash, str(user.id)

    if stored_hash is not None:
        ok = bcrypt.checkpw(body.password.encode(), stored_hash.encode())
    else:
        bcrypt.checkpw(body.password.encode(), _dummy_hash())  # 等时:未知邮箱不提前返回
        ok = False
    if not ok:
        return _unauthorized("邮箱或密码错误")

    email = (staff or user).email
    return {
        "success": True,
        "data": {"user": {"id": subject, "email": email}, "token": issue_token(subject, email)},
    }


@router.post("/api/auth/register")
async def register(body: RegisterIn):
    """商城用户注册:engine users 建账号(bcrypt)+ 商户客户档案联动建档
    (customer_id 供订单/优惠券绑定);邮箱唯一,密码 ≥ 8 位。"""
    email = body.email.strip().lower()
    if "@" not in email or len(email) < 5:
        return JSONResponse(status_code=400, content={"success": False, "message": "邮箱格式不正确"})
    if len(body.password) < 8:
        return JSONResponse(status_code=400, content={"success": False, "message": "密码至少 8 位"})

    async with get_session() as session:
        exists = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if exists is not None:
            return JSONResponse(status_code=409, content={"success": False, "message": "该邮箱已注册,请直接登录"})
        password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
        user = User(email=email, password_hash=password_hash)
        session.add(user)
        await session.commit()
        await session.refresh(user)

    # 商户客户档案联动(订单/优惠券按 customer_id 绑定);商户库不可达不阻断注册
    customer_id = ""
    try:
        import uuid as _uuid

        from engine_py.tools_registry.order_domain import _merchant_writer_engine
        from sqlalchemy import text as _t

        from gateway_py.merchant_db import ensure_merchant_tables

        await ensure_merchant_tables()
        customer_id = f"CUST-{_uuid.uuid4().hex[:8].upper()}"
        display = body.displayName.strip() or email.split("@")[0]
        async with _merchant_writer_engine().begin() as conn:
            await conn.execute(
                _t(
                    "INSERT INTO merchant_customers (customer_id, name, phone, member_level) "
                    "VALUES (:cid, :n, :p, 'VIP')"
                ).bindparams(cid=customer_id, n=display, p="")
            )
    except Exception as err:
        logging.getLogger(__name__).warning("注册客户档案建档失败: %s", err)

    return {
        "success": True,
        "data": {
            "user": {"id": str(user.id), "email": email, "customerId": customer_id},
            "token": issue_token(str(user.id), email),
        },
    }


@router.post("/api/auth/logout")
async def logout(authorization: str | None = Header(None)):
    claims = await _resolve_bearer(authorization)
    if isinstance(claims, JSONResponse):
        return claims

    remaining = max(int(claims.get("exp", 0)) - int(_dt.datetime.now(tz=_dt.UTC).timestamp()), 1)
    await (await get_redis()).set(_DENY_PREFIX + claims["jti"], "1", ex=remaining)
    return {"success": True}


@router.get("/api/auth/me")
async def me(authorization: str | None = Header(None)):
    claims = await _resolve_bearer(authorization)
    if isinstance(claims, JSONResponse):
        return claims

    # 按 email 回查当前真实记录(员工/平台账号均可;0013 附带员工角色):
    # 物理库 re-seed 后 sub 里的旧 UUID 漂移在此自愈
    async with get_session() as session:
        staff = (
            await session.execute(select(StaffMember).where(StaffMember.email == claims.get("email")))
        ).scalars().first()
        user = (
            await session.execute(select(User).where(User.email == claims.get("email")))
        ).scalar_one_or_none()
    identity = staff if staff is not None else user
    if identity is None:
        return _unauthorized("账号已不存在")

    payload = {"id": str(identity.id), "email": identity.email}
    if staff is not None:
        payload["role"] = staff.role
    return {"success": True, "data": {"user": payload}}
