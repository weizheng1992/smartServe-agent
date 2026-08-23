---
description: 数据库 Schema 设计、多租户隔离约束、规范化关联与 Drizzle ORM 开发规范
paths: ["packages/db/**/*", "drizzle.config.ts"]
---

# 数据库与 ORM 规范 (Database & ORM)

本工作区负责 PostgreSQL 物理数据库建模、多租户数据安全策略、实体规范化关联以及 Drizzle ORM 客户端交互。

## 1. 核心架构与数据建模

### 1.1 纯 PostgreSQL 单一真实数据源

- **连接池架构**：通过 `packages/db/src/client.ts` 直连真实物理 PostgreSQL（`pg.Pool`），杜绝任何伪造内存 Mock 存储。
- **Schema 统一管理**：全部数据表集中在 `packages/db/src/schema.ts` 声明。

### 1.2 核心数据表分区

1. **用户与会话体系**：
   - `users`：全局平台用户主表。
   - `threads`：会话上下文表（关联 `userId` 与 `businessId`）。
   - `messages`：会话消息明细表（维护严谨的时序索引）。
2. **电商与规范化收货地址模型**：
   - `userAddresses`：规范化用户地址簿（`id` UUID, `userId`, `recipientName`, `phone`, `province`, `city`, `district`, `detailAddress`, `isDefault`）。
   - `orders`：订单主表。**强制规范化设计**：包含 `addressId`（严格外键关联 `userAddresses.id`），禁止冗余平铺原始地址文本。
   - `products`、`productSkus`、`orderItems`：商品、SKU 与订单行明细。
   - `logisticsPackages`、`logisticsTracks`：物流包裹与运单实时轨迹节点。
   - `afterSaleTickets`、`afterSaleLogs`：售后工单与流转操作审计记录。
3. **四象限记忆与多租户画像表**：
   - `longMemoryFacts`：客户长周期画像事实表，包含 `scope`（`'global'` 全局 / `'tenant'` 租户专属）、`businessId` 以及 `embedding` 向量字段。
   - `episodicEvents`：情境记忆事件，包含重要性权重分与向量索引。
   - `taskMemory`：智能体任务步骤与规划暂存表。
4. **SaaS 知识库与 Contextual RAG**：
   - `ragDocuments`：知识切片表，包含 `businessId`、`contextualSummary` 全局摘要前缀、`chunkText` 正文与向量索引。
5. **HITL 审批与事务发件箱（Outbox）**：
   - `pendingApprovals`：人工安全审核挂起单据。
   - `approvalOutboxEvents`：审批恢复事务发件箱表（包含 `status: 'pending' | 'processing' | 'completed' | 'failed'`、`payload`、`retryCount`、`processedAt`）。
6. **SaaS 租户与动态工具集成**：
   - `tenants`、`tenantConfigs`、`tenantMembers`、`tenantTools`、`businessConfigs`：商户租户主体、KMS 加密凭证与 OpenAPI 动态工具注册配置。
7. **可观测性与评测体系**：
   - `llmCallLogs`：大模型细粒度 Token 消耗、耗时、模型版本与 Prompt 快照。
   - `lowConfidenceLogs`：意图分类低置信度日志与消歧归档。
   - `sessionMetrics`、`evalRuns`、`evalResults`：会话质量指标与自动化评测集结果。

---

## 2. 数据库设计与编码准则

1. **强制租户隔离约束**：
   - 编写任何业务查询或变更操作时，必须显式在 WHERE 条件中注入 `businessId`（`business_id`），防止 SaaS 跨租户越权。
2. **规范化外键与 JOIN 查询**：
   - 获取订单收发货信息时，严禁使用过时平铺字段，必须使用 `orders.addressId = userAddresses.id` 进行 JOIN 关联。
3. **类型同步联动**：
   - 当在 `schema.ts` 中增删字段或修改表结构后，必须同步更新 `packages/types/src/db.ts` 及其他关联契约类型。
4. **Schema 迁移维护流程**：
   - 严禁手动篡改数据库原生表结构。
   - 生成迁移文件：`bun drizzle-kit generate`
   - 同步至数据库：`bun drizzle-kit push`
