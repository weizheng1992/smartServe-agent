"""FastAPI 网关装配 — 镜像 apps/server AppModule(39 路由 + SSE + socket.io + 统一异常)。

运行::

    uvicorn gateway_py.main:app --port 4000
"""

from __future__ import annotations

from engine_py.llm import warm_embedding_model_in_background
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from socketio import ASGIApp

from .realtime import sio
from .routers import admin, chat, crud, merchant, spi
from .tenant_context import TenantContextMiddleware, _PermissionError

fastapi_app = FastAPI(title="agent-all gateway-py", version="0.1.0")

fastapi_app.add_middleware(TenantContextMiddleware)
# CORS:对齐 TS 基线 AppModule 与 server-gateway.md §1.1(移植时遗失)。
# web(3000)/admin(3001)/merchant(3005) 为独立 origin 的 SPA,api 客户端默认绝对地址
# http://localhost:4000(绕过各自 Vite proxy),预检与响应须由网关放行;缺失时浏览器侧
# 全部 fetch 失败、前端静默回退演示假数据(tenants 页 INITIAL_TENANTS 即此症状)。
# 后注册使 CORS 位于最外层,TenantContextMiddleware 的 403 响应也带 CORS 头。
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", "http://localhost:3005"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@fastapi_app.exception_handler(_PermissionError)
async def permission_error_handler(request: Request, exc: _PermissionError):
    return JSONResponse(status_code=403, content={"statusCode": 403, "message": "Forbidden: tenant context required"})


@fastapi_app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"statusCode": 400, "message": str(exc)})


@fastapi_app.get("/api/health")
async def health():
    return {
        "success": True,
        "status": "ok",
        "service": "gateway-py",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    }


fastapi_app.include_router(crud.router)
fastapi_app.include_router(admin.router)
fastapi_app.include_router(admin.approvals_router)
fastapi_app.include_router(chat.router)
fastapi_app.include_router(spi.router)
fastapi_app.include_router(merchant.router)

# socket.io 挂载在默认 path /socket.io,namespace /ws/chat;其余路径回落到 FastAPI
app = ASGIApp(sio, other_asgi_app=fastapi_app)

# 本地 embedding 预热:首次构造含 torch 加载与网络回退,交由后台线程承担,
# 避免首个向量化请求在事件循环线程同步执行(受限网络下曾致网关整体冻结)
warm_embedding_model_in_background()
