---
description: PostgreSQL Drizzle ORM 数据建模、多租户物理隔离、事务发件箱与幂等迁移规范
paths: ["packages/db/**/*"]
---

# 数据库与数据持久层规范 (Database & Schema)

本工作区负责 PostgreSQL 物理数据模型定义、Drizzle ORM 映射、租户数据物理隔离、事务发件箱事件表及幂等迁移。

## 1. 核心模型与架构规范

### 1.1 核心数据表与职责划分

1. **会话与消息体系**：
   - `conversations`：会话元数据（包含 `business_id`、`user_id`、`status`、`is_takeover` 人工接管标记、`takeover_admin_id`）。
   - `messages`：历史轮次物理持久化（`role`、`content`、`cards` 多模态结构化 JSONB）。
2. **多租户与商户配置**：
   - `tenants`：租户主表（`business_id`、`name`、`api_key`、`skills_config` 技能重载 JSONB、`enabled_skills` 数组）。
3. **客户关系与地址标准化**：
   - `users`：客户档案表（`user_id`、`name`、`email`、`phone`、`default_address_id`）。
   - `addresses`：规范化地址实体表（`recipient_name`、`phone`、`province`、`city`、`district`、`detail_address`、`postal_code`）。
4. **电商核心业务表**：
   - `orders`：订单主表（`order_id`、`business_id`、`user_id`、`status`、`amount`、`address_id`）。
   - `order_items`：订单商品明细表。
   - `products`：商品知识与库存表。
5. **记忆与画像隔离表**：
   - `persona_memories`：双层用户画像（`user_id`、`scope: 'global' | 'tenant'`、`business_id`、`traits` JSONB）。
   - `long_memory_facts`：长期偏好向量表（支持 pgvector 索引）。
   - `episodic_memories`：重大事件记忆表。
6. **审批与事务发件箱 (HITL & Outbox)**：
   - `pending_approvals`：待人工审核记录（`approval_id`、`business_id`、`job_id`、`tool_name`、`status`）。
   - `approval_outbox_events`：事务发件箱事件表（`event_type`、`payload`、`status: 'pending' | 'processing' | 'completed' | 'failed'`、`retry_count`）。

### 1.2 多租户物理隔离约束

- **强制租户外键**：除用户全局属性（`users`、`scope = 'global'` 的记忆）外，所有业务数据表（`orders`、`conversations`、`pending_approvals` 等）必须包含 `business_id` 字段。
- **查询与写入防泄漏**：所有 Drizzle 查询必须强制附带 `eq(table.businessId, tenantId)` 条件，禁止无租户限定的裸查。

### 1.3 事务发件箱模式 (Transactional Outbox Pattern)

- 任何高危状态机变更（如批准退款、拒绝申请、修改收货地址）必须在同一个 Drizzle 事务中，原子性地写入 `pending_approvals` 更新与 `approval_outbox_events` 事件生成，彻底杜绝分布式事务丢单。

---

## 2. 迁移与编码准则

1. **类型一致性**：主键和外键统一使用 PostgreSQL `text` 或 `uuid`，时间字段统一使用 `timestamp("created_at", { withTimezone: true }).defaultNow()`。
2. **幂等迁移脚本**：字段变更优先通过 `packages/db/src/migrateColumns.ts` 编写带 `IF NOT EXISTS` 的幂等 SQL 脚本执行，避免非受控变更破坏存量测试数据。
3. **禁止在模型中写业务逻辑**：`packages/db/src/schema.ts` 纯粹承载表结构与关系映射，严禁在 ORM 定义层耦合状态机或 LLM 提示词。
