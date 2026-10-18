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
        body_tenant: str | None = None
        if not raw_tenant_id and request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.json()
                if isinstance(body, dict):
                    body_tenant = body.get("tenantId") or body.get("businessId")
                    raw_tenant_id = body_tenant
            except Exception:
                pass
        if not raw_tenant_id and raw_role == "admin":
            raw_tenant_id = "all"

        user_id = request.headers.get("x-user-id") or request.query_params.get("userId") or "anonymous"
        # provenance(2026-10-18 闸族收口):租户来源显式化 —— 消费方(及审计)
        # 可区分「真带租户头」与「admin 缺省 all/自报」,伪造面可断言
        if request.headers.get("x-tenant-id") or request.headers.get("x-business-id"):
            source = "header"
        elif request.query_params.get("tenantId") or request.query_params.get("businessId"):
            source = "query"
        elif body_tenant:
            source = "body"
        elif raw_role == "admin":
            source = "admin-default"
        else:
            source = "none"
        payload = {
            "tenantId": (raw_tenant_id or "").strip(),
            "userId": user_id.strip(),
            "role": raw_role.strip(),
            "source": source,
        }
        request.state.tenant = payload
        token = _current_tenant.set(payload)
        try:
            return await call_next(request)
        finally:
            _current_tenant.reset(token)


# require_tenant_context/_PermissionError 双胞胎已退役(2026-10-18 闸族收口):
# 无租户上下文的 403 呈现统一 {"detail"} 形(两形规则的 detail 半边),由
# tenant_scope.staff_context Depends 承担;本模块只剩 middleware + 读取器。
