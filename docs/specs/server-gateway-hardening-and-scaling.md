# Feature Specification: Server Gateway Security Hardening, Distributed Realtime Takeover & Reliable Streaming

## Problem Statement

当前智能客服服务端 API 网关虽然建立了基础的 NestJS 模块化与多租户上下文流转，但在生产环境高并发、多实例水平扩展以及多商户集成场景下存在以下隐患：

1. **租户边界与鉴权漏洞**：中间件对缺少 Tenant Header 的请求默认放行并赋予操作员角色，商户 SPI 缺乏严格的 HMAC-SHA256 签名与时间戳防重放校验，存在跨租户数据越权与伪造请求风险。
2. **WebSocket 单机内存瓶颈**：在线客服坐席接管与房间连接元数据存储于单机内存，多实例部署时无法实现跨节点的房间状态同步与协同广播。
3. **输入校验与防刷机制缺失**：接口层缺少全局 DTO 严格白名单校验管道，核心大模型对话与 SPI 接口缺乏租户级频率限制（Rate Limiting），易遭恶意刷量消耗 Token 账单。
4. **SSE 流式弱网韧性不足**：Temporal 轮询模式采用固定高频查询，且推流未支持事件序号与断线续传，弱网断连后易丢失中间输出。

## Solution

通过全面加固 NestJS 服务端网关，构建具备**金融级安全防护、多实例分布式实时协同、自适应限流熔断与高韧性流式推流**的企业级 Gateway：

1. **多租户安全防护与 HMAC 签名核签体系**：强制严格租户上下文识别，接入 KMS 派生密钥与 HMAC-SHA256 签名防重放网关。
2. **基于 Redis 适配器的分布式 WebSocket 协同总线**：挂载 WS 握手鉴权中间件，利用 Redis Pub/Sub 实现跨多实例的房间广播与人工坐席无感接管。
3. **全局 DTO 校验与租户自适应防刷限流**：开启全局 ValidationPipe 深度校验，引入 Throttler 实施基于租户与 IP 的滑动窗口限流。
4. **可靠 SSE 打字机流式总线**：引入 EventId 序号递增、心跳自愈与基于 Redis 事件通知的高性能低延迟推流架构。

---

## User Stories

1. As a platform security engineer, I want all incoming HTTP and WebSocket requests to be strictly validated against authenticated tenant boundaries, so that cross-tenant IDOR leaks and unauthenticated access are completely blocked.
2. As a merchant developer, I want all SPI approval and escalation API calls to require HMAC-SHA256 signature verification and a timestamp within a 300-second window, so that replay attacks and forged webhook payloads are rejected.
3. As a customer service operator, I want to take over customer sessions in real-time across multiple load-balanced server instances, so that I can assist customers seamlessly without message loss.
4. As an end-user on mobile web, I want the SSE typing stream to automatically recover lost tokens using `Last-Event-ID` upon network reconnection, so that I don't see broken or truncated AI responses.
5. As a platform administrator, I want chat dispatch endpoints to enforce rate limits per tenant and IP, so that rogue clients cannot exhaust our LLM quota or spike operating costs.
6. As a backend developer, I want all controller incoming payloads to be validated and sanitized with strict DTO rules, so that invalid or malicious properties are stripped before reaching domain services.
7. As a customer service manager, I want operator typing indicators and takeover status events to broadcast reliably to all participants in the thread room, so that both agents and users have real-time visibility into the dialogue state.
8. As a site reliability engineer, I want the server gateway to maintain active health checks and structured request logging with trace IDs, so that system anomalies can be debugged immediately.
9. As an API consumer, I want consistent JSON error responses with clear error codes and localized messages, so that client applications can handle business exceptions gracefully.
10. As a store merchant, I want to safely close escalated tickets via API, so that the AI decision engine automatically resumes control with appropriate closing messages.

---

## Implementation Decisions

### 1. 租户识别与安全守卫增强 (Tenant Security & Guard Hardening)

- **严格租户提取与校验**：废弃隐式默认 `ecommerce` 兜底策略，在需要租户上下文的路由上强制要求有效租户标识（Header / API Key），缺失时显式返回 `401 Unauthorized` 或 `400 Bad Request`。
- **商户 SPI HMAC-SHA256 验签闭环**：
  - `MerchantSpiService` 完整接入 `HmacSigner`。
  - 提取请求头 `x-signature`、`x-timestamp` 与 `x-api-key`，校验 `abs(now - timestamp) <= 300s`。
  - 基于租户私钥计算 Payload 摘要并进行恒定时间比对（`crypto.timingSafeEqual`），防止时序侧信道攻击。

### 2. 分布式 WebSocket 协同总线架构 (Distributed Socket.IO Redis Adapter)

- **Redis Adapter 跨节点广播**：
  - 为 `ConversationGateway` 配置 `@socket.io/redis-adapter`，依赖现有 Redis 实例。
  - 所有房间广播事件（`new_message`, `conversation_state_changed`, `user_typing`, `peer_joined`）通过 Redis Pub/Sub 分发至集群所有网关节点。
- **WS 握手鉴权与中间件**：
  - 在 Socket.io 连接阶段校验 `handshake.auth`（Token / TenantId / Role），非法连接在握手期直接拒绝。

### 3. 全局 DTO 运行时校验与租户滑动窗口限流 (Validation & Rate Limiting)

- **全局 ValidationPipe**：
  - `main.ts` 中注册 `ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })`。
  - 所有 Controller DTO 采用 `class-validator` 显式注解约束（`IsString`, `IsNotEmpty`, `IsOptional`, `IsEnum`, `IsArray` 等）。
- **租户粒度防刷限流 (Throttler)**：
  - 集成 `@nestjs/throttler`，基于 Redis 存储记录访问频次。
  - 核心对话接口 `/api/chat` 限制为 60 req/min，商户 SPI 接口限制为 300 req/min。

### 4. 高韧性可靠 SSE 推流架构 (Reliable SSE Stream Bus)

- **递增事件序号 (`eventId`)**：每个 SSE 发送的 Thought/Tool/Result 均附加递增序列号。
- **支持 `Last-Event-ID` 断线续传**：客户端重连带上上次接收的事件 ID 时，服务网关优先从短期内存缓存或 Redis 中重放缺失事件，保障打字机无损连贯。
- **Temporal 轮询降载**：结合事件驱动设计，在工作流触发关键状态变更时主动发信，降低高频轮询对 Temporal Frontend 的压力。

---

## Testing Decisions

### 1. 测试质量与原则 (Testing Principles)

- **纯外部黑盒行为测试**：针对 Controller 接口和 Gateway WebSocket 进行端到端 HTTP / Socket 行为测试，避免侵入内部临时变量。
- **多租户越权与防伪对抗测试**：测试恶意构造空租户、篡改商户 HMAC 签名、超期时间戳等场景，断言严格 401/403 阻断。
- **并发与分布式广播测试**：模拟多个 WebSocket 客户端加入同一 `thread` 房间，验证在跨节点场景下消息收发与接管状态 100% 同步。

### 2. 测试覆盖模块

- `apps/server/test/tenantSecurity.test.ts`：租户上下文鉴权中间件与 Guard 边界。
- `apps/server/test/merchantSpiHmac.test.ts`：商户 SPI HMAC 签名计算、时间戳窗口与防篡改验证。
- `apps/server/test/conversationGatewayDistributed.test.ts`：Socket.io 握手、房间广播与接管状态机。
- `apps/server/test/chatSseResiliency.test.ts`：SSE 管道推流、心跳保活与断线重放机制。

### 3. 参考既有资产 (Prior Art)

- `packages/tools/tests/merchantSpiConnector.test.ts` (HMAC 签名算法标准)
- `apps/server/test/conversationGateway.test.ts` (WebSocket 基础单测)
- `apps/server/test/chatService.test.ts` (对话分发单测)

---

## Out of Scope

1. **底层大模型 Prompt 模板优化与 Agent 图拓扑调整**（属于 `packages/engine` 范畴）。
2. **管理后台前端页面重构与 UI 组件改动**（属于 `apps/admin` 与 `packages/ui` 范畴）。
3. **数据库物理表 DDL 重大重构**（复用现有 Drizzle schema）。

---

## Further Notes

- 网关所有改动保持与 `apps/web` 客户端以及 `apps/admin` 管理后台控制平面的 API 契约向后兼容。
- Redis 连接复用已有基础设施配置（`process.env.REDIS_URL`），无需引入额外存储中间件。
