"""租户上下文 — 镜像 common/tenant/(middleware + guard),contextvars 版。

中间件从 header/query/body 解析租户身份注入上下文;
guard 要求非空 tenantId(或 admin 角色),否则 403。
"""

from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

_current_tenant: ContextVar[dict | None] = ContextVar("current_tenant", default=None)


def get_tenant_context() -> dict | None:
    return _current_tenant.get()


def get_tenant_id() -> str:
    ctx = _current_tenant.get() or {}
    return str(ctx.get("tenantId") or "")


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        raw_role = request.headers.get("x-role", "user")
        raw_tenant_id = (
            request.headers.get("x-tenant-id")
            or request.headers.get("x-business-id")
            or request.query_params.get("tenantId")
            or request.query_params.get("businessId")
        )
        if not raw_tenant_id and request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.json()
                if isinstance(body, dict):
                    raw_tenant_id = body.get("tenantId") or body.get("businessId")
            except Exception:
                pass
        if not raw_tenant_id and raw_role == "admin":
            raw_tenant_id = "all"

        user_id = request.headers.get("x-user-id") or request.query_params.get("userId") or "anonymous"
        payload = {
            "tenantId": (raw_tenant_id or "").strip(),
            "userId": user_id.strip(),
            "role": raw_role.strip(),
        }
        request.state.tenant = payload
        token = _current_tenant.set(payload)
        try:
            return await call_next(request)
        finally:
            _current_tenant.reset(token)


def require_tenant_context() -> dict:
    """镜像 TenantGuard:无租户上下文(且非 admin)→ 403。"""
    ctx = get_tenant_context()
    if ctx and ctx.get("tenantId"):
        return ctx
    raise _PermissionError()


class _PermissionError(Exception):
    pass
