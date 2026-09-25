"""FastAPI 网关装配 — 镜像 apps/server AppModule(39 路由 + SSE + socket.io + 统一异常)。

运行::

    uvicorn gateway_py.main:app --port 4000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from engine_py.llm import warm_embedding_model_in_background
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from socketio import ASGIApp

from .rate_limit import RateLimitMiddleware
from .realtime import sio
from .routers import admin, analytics, auth, chat, crud, merchant, spi
from .tenant_context import TenantContextMiddleware, _PermissionError


async def _sync_product_knowledge_on_startup() -> None:
    """商品知识 RAG 同步(2026-09-13):商户真货架 → rag_documents,启动时
    幂等重建 —— 商户改标题/价格后重启生效;商户库未 seed 时诚实跳过。

    挂载身份 = 货架属主 ``_merchant_id()``(2026-09-25 帐篷幻觉收口):此前
    硬编码演示租户 "ecommerce",aurora 检索被 rag_documents.business_id
    物理过滤,看不见自己的货架 → finish 零商品事实即编造商品与价格;反向
    还构成跨租户串味(ecommerce 能引用 aurora 的在售货架)。
    """
    try:
        from engine_py.rag.product_knowledge import sync_product_knowledge

        from .merchant_domain import _merchant_id

        result = await sync_product_knowledge(_merchant_id())
        print(f"[Startup] Product knowledge RAG synced: {result}")
    except Exception as startup_err:
        print(f"[Startup] Product knowledge sync skipped: {startup_err}")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await _sync_product_knowledge_on_startup()
    yield


fastapi_app = FastAPI(title="agent-all gateway-py", version="0.1.0", lifespan=_lifespan)

# 限流最先注册 → 位于最内层:须在 TenantContextMiddleware 解析完 request.state.tenant
# 之后运行,与 guard 同一租户口径;只挂 /api/chat 与 /api/v1/spi 高频入口。
fastapi_app.add_middleware(RateLimitMiddleware)
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
fastapi_app.include_router(auth.router)
fastapi_app.include_router(chat.router)
fastapi_app.include_router(spi.router)
fastapi_app.include_router(merchant.router)
fastapi_app.include_router(analytics.router)
fastapi_app.include_router(merchant.merchant_promotions_router)

# 聊天图片静态服务(wayfinder multimodal-image-chat 002):上传端点回 /api/uploads/ URL,
# 前端经既有 /api 代理直达;目录由 chat 模块导入时确保存在
fastapi_app.mount("/api/uploads", StaticFiles(directory=str(chat.UPLOADS_DIR)), name="chat-uploads")

# socket.io 挂载在默认 path /socket.io,namespace /ws/chat;其余路径回落到 FastAPI
app = ASGIApp(sio, other_asgi_app=fastapi_app)

# 本地 embedding 预热:首次构造含 torch 加载与网络回退,交由后台线程承担,
# 避免首个向量化请求在事件循环线程同步执行(受限网络下曾致网关整体冻结)
warm_embedding_model_in_background()
