"""Auth 路由 — /api/auth/login|logout|me(web 真实登录链路)。

新增于 39 条冻结路由之外(冻结契约只约束既有路由形状);本组契约由
tests/test_http_routes_contract.py 的 auth 用例钉死。

- 凭证:``users.password_hash``(bcrypt;seed 以 E2E_ACCOUNT_PASSWORD 覆写种子账号)。
- 会话:JWT HS256 长过期(默认 30 天,无刷新),claims 携带 sub/email/jti。
- 登出:Redis jti 黑名单(TTL 截止 token 自然过期),``/api/auth/me`` 拒绝已登出 token。
- 邮箱不存在与密码错误统一 401 文案(防账号枚举),并对未知邮箱做等时 dummy 校验。
- 成功载荷走统一信封 ``{success, data: {user, token}}``(server-gateway §1.4)。
"""

from __future__ import annotations

import datetime as _dt
import functools
import logging
import os
import uuid

import bcrypt
import jwt
from engine_py.db import User, get_session
from engine_py.event_bus import get_client as get_redis
from fastapi import APIRouter, Header
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


@functools.lru_cache(maxsize=1)
def _dummy_hash() -> bytes:
    """等时防枚举:邮箱不存在时也走一次 bcrypt 校验,抹平响应时间差。"""
    return bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt())


def _unauthorized(message: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"success": False, "error": message})


def _issue_token(user: User) -> str:
    now = _dt.datetime.now(tz=_dt.UTC)
    claims = {
        "sub": str(user.id),
        "email": user.email,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + _dt.timedelta(days=_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(claims, _JWT_SECRET, algorithm="HS256")


async def _resolve_bearer(authorization: str | None) -> dict | JSONResponse:
    """校验 Bearer JWT;坏 token / 黑名单 token → 401 响应,否则返回 claims。"""
    if not authorization or not authorization.startswith("Bearer "):
        return _unauthorized("缺少 Bearer 凭证")
    try:
        claims = jwt.decode(authorization.removeprefix("Bearer "), _JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return _unauthorized("凭证无效或已过期")
    if await (await get_redis()).get(_DENY_PREFIX + claims.get("jti", "")):
        return _unauthorized("凭证已登出")
    return claims


@router.post("/api/auth/login")
async def login(body: LoginIn):
    async with get_session() as session:
        user = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()

    if user is not None and user.password_hash:
        ok = bcrypt.checkpw(body.password.encode(), user.password_hash.encode())
    else:
        bcrypt.checkpw(body.password.encode(), _dummy_hash())  # 等时:未知邮箱不提前返回
        ok = False
    if not ok:
        return _unauthorized("邮箱或密码错误")

    return {
        "success": True,
        "data": {"user": {"id": str(user.id), "email": user.email}, "token": _issue_token(user)},
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

    # 按 email 回查当前真实记录:物理库 re-seed 后 sub 里的旧 UUID 漂移在此自愈
    async with get_session() as session:
        user = (
            await session.execute(select(User).where(User.email == claims.get("email")))
        ).scalar_one_or_none()
    if user is None:
        return _unauthorized("账号已不存在")

    return {"success": True, "data": {"user": {"id": str(user.id), "email": user.email}}}
