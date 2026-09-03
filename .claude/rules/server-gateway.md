---
description: FastAPI 多租户 API 网关、实时会话与人工协同接入、Skills 配置管理接口规范
paths: ["services/gateway-py/**/*"]
---

# 服务端多租户网关与实时协同规范 (Server Gateway)

本服务是整个平台的服务端 API 网关，基于 FastAPI 构建（`services/gateway-py/src/gateway_py/`），负责多租户路由转发、实时人工客服协同接管 (Live Takeover)、Skills 技能与工具配置同步、会话流式推送与审计追踪。39 条 HTTP 路由与 SSE/socket.io 线格式已冻结（pytest 契约测试为唯一真实来源）。

## 1. 核心模块与架构规范

### 1.1 模块职责划分

1. **`main.py`**：FastAPI 应用装配（CORS、路由注册、socketio ASGI 挂载、lifespan 连接池管理）。
2. **`routers/chat.py`**：
   - 智能体作业受理（入队 Redis Stream / 直跑）与 SSE 事件流端点（`Last-Event-ID` 断线重连回放，事件源为 Redis Streams 本身）。
   - 会话消息持久化与历史拉取（多租户过滤）。
3. **`routers/admin.py` / `crud.py`**：
   - 会话历史、审批单（Approve / Reject，触发事务发件箱与幂等恢复）、Skills 配置（`GET/PUT /api/skills/config`）、RAG 文档、画像、护栏、计费配额、日志等管理端 CRUD。
   - 数据真实性约定（2026-09-03 起）：`/api/evals/*` 记录由本地随机生成器写入，响应显式携带 `isMock: true`（坏例看板/BI 须据此排除）；`/api/logs` 消费 `session_metrics`/`intent_logs` 真实值，无遥测数据处返回真实 0，**严禁编造 token/延迟数字**。
   - 画像事实删除（`DELETE /api/personas/{id}`）在删除成功后调用 `engine_py.badcase.pool.record_badcase_signal` 入坏例候选池（失败静默降级，不影响删除响应）。
4. **`routers/merchant.py` + `merchant_domain.py` / `merchant_db.py`**：商户门户店铺端与管理端路由及领域逻辑（原 Next.js Route Handlers 移植）。
5. **`routers/spi.py` + `hmac_signer.py`**：三方 SPI v1 开放接口（HMAC-SHA256 签名 + 时间戳防重放校验）。

### 1.2 实时协同 (realtime.py)

- **socket.io 房间模型**：operator + user 双客户端按 `thread:{threadId}` 房间接入；joined_room ack 仅回发送者，`peer_joined` 房间广播。
- **接管状态机**：`takeover` / `release`（支持 `"__unset__"` 哨兵显式清空坐席字段）→ 广播 `conversation_state_changed`；`send_message` → `new_message` + ack；`typing` 事件 `skip_sid` 排除发送者本人。
- **租户校验**：`tenantId` 正则 `^[a-zA-Z0-9_-]{1,64}`，非法直接拒绝连接。

### 1.3 多租户鉴权与上下文传递

- **租户识别**：通过 Request Header（如 `x-tenant-id`, `x-business-id`）或 Bearer Token 解析租户上下文（`tenant_context.py`）。
- **请求生命周期隔离**：所有路由与 Service 函数必须显式接收并传递 `tenant_id`，严禁使用全局可变状态承载租户。

### 1.4 统一响应与异常处理规范

- **统一 JSON 响应格式**：`{ success: boolean, data?: any, error?: string, message?: string }`（冻结契约，字段名与 TS 基线一致）。
- **业务异常与 HTTP 状态码**：非法租户返回 403 Forbidden，资源未找到返回 404 Not Found，参数校验失败返回 400 Bad Request（Pydantic 校验即 422 之外的手写分支）。

---

## 2. 编码与维护准则

1. **依赖注入显式化**：FastAPI `Depends` 提供会话/连接池，跨模块调用通过显式参数传递，不引入全局单例服务注册表。
2. **DTO 严格校验**：所有接收客户端输入的主体必须使用 Pydantic 模型定义清晰的 DTO（字段名保持与 TS 契约一致的 camelCase 输出）。
3. **契约测试先行**：新增或修改路由时，必须在 `services/gateway-py/tests/test_http_routes_contract.py` / `test_realtime_contract.py` 同步维护用例；契约改动需同步前端 `packages/types`。
4. **不跑测试**：本仓库当前约定由人工触发 pytest（`bun run test:eval`），Claude 修改后仅做语法检查。
