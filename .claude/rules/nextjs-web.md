---
description: Next.js 客户端前端、会话生命周期、SSE 流式传输、富交互卡片与多模态上传规范
paths: ["apps/web/**/*"]
---

# Next.js 客户端应用规范 (Web Client)

本工作区负责面向终端用户的聊天界面、会话生命周期管理、SSE 实时流式传输、多模态图片上传与富交互卡片渲染。

## 1. 核心架构与功能流转

### 1.1 客户端动态 UUID v4 会话派发

- **零 Fallback 级安全隔离**：用户打开页面时，浏览器端通过 `crypto.randomUUID()` 动态派发唯一的 `threadId`，物理写入 PostgreSQL，杜绝使用任何静态共享会话导致的多用户数据串扰。
- **双向 URL 同步**：通过 `window.history.replaceState` 实现当前 `threadId` 与浏览器地址栏参数 `?threadId=...` 的秒级双向同步，刷新或保存书签时无缝恢复上下文。

### 1.2 核心 API 路由体系

- **`POST /api/chat`**：
  - 接收用户文本消息及可选的多模态图片链接（`imageUrls`）。
  - 创建并初始化 Agent 任务作业，返回唯一的 `jobId`。
- **`GET /api/chat/[jobId]/stream` (SSE 实时流)**：
  - 接入 Server-Sent Events (SSE) 事件通道。
  - 优先监听 Temporal 工作流进度；在本地降级模式下订阅 LangGraph `agentEventEmitter`。
  - 推送标准化事件流（`thought` 思考步骤、`tool` 工具调用、`approval_required` 审批挂起、`result` 最终回复及 `cards` 结构化卡片数据）。
  - 必须保持 15 秒心跳保活（Heartbeat），防止代理服务器或网关超时断连。
- **`GET /api/chat/orders`**：
  - 查询指定用户的订单历史记录（入参：`userId` 与 `businessId`）。
  - 通过领域服务（`orderDomainService`）返回包含规范化收货地址（`userAddresses`）及商品明细的结构化数据。
- **`POST /api/chat/upload`**：
  - 处理多模态售后图片上传，存储并生成公开静态访问路径供视觉分析模型处理。

### 1.3 富交互卡片家族与渲染体系 (`@agent-all/ui`)

- **`RichCardRenderer` 统一容器**：
  - `OrderCard`：订单基础信息、发货状态与金额。
  - `TrackingTimeline`：物流轨迹可视化时间轴。
  - `RefundConfirmationCard`：退款核签与赔付凭证卡。
  - `DamageAssessmentCard`：AI 视觉多模态定责与瑕疵评估卡。
  - `QuickReplies`：快捷回复胶囊与意图确认按钮。
- **确定性消息时序**：前端消息列表基于自增/时间戳严格保序，防止流式并发时乱序闪烁。

### 1.4 人工接管（Takeover）状态机

- 当后台客服或审核人员执行 Takeover 人工接管时，前端通过轮询或流式通道感知状态流转。
- 界面即时显示人工客服已接入提示条，并根据接管状态锁定或开放用户输入框。

---

## 2. 编码与前端准则

1. **严格参数校验**：所有 API 路由必须校验 `threadId`、`businessId` 与 `userId` 的合法性。
2. **轻量化 API Route**：严禁在 Next.js Route Handler 中执行高耗时阻塞计算，复杂计算必须下沉至 `packages/engine`。
3. **样式与组件复用**：基于 Tailwind CSS v4 与 `@agent-all/ui` 构建界面，保持设计系统统一。
4. **流式容灾处理**：SSE 客户端需具备断线重连、心跳超时检测以及错误状态友好 Toast 提示。
