---
description: PostgreSQL SQLAlchemy 数据建模、Alembic 迁移、多租户物理隔离、事务发件箱规范
paths: ["services/engine-py/src/engine_py/db/**/*", "services/engine-py/alembic/**/*"]
---

# 数据库与数据持久层规范 (Database & Schema)

本模块负责 PostgreSQL 物理数据模型定义（`services/engine-py/src/engine_py/db/models.py`，SQLAlchemy）、Alembic 迁移（`services/engine-py/alembic/`）、租户数据物理隔离、事务发件箱事件表。数据库 schema 所有权自 2026-09 起由 Alembic 接管（原 Drizzle `db:push` 已退役）。

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
   - `pending_approvals`：待人工审核记录（`approval_id`（UUID）、`business_id`、`job_id`、`tool_name`、`status`）。
   - `approval_outbox_events`：事务发件箱事件表（`event_type`、`payload`、`status: 'pending' | 'processing' | 'completed' | 'failed'`、`retry_count`）。
7. **遥测**：`session_metrics` 会话成本遥测（Token 用量与 USD 成本换算落盘）；2026-09-03 起新增 `global_transitions_count` / `tool_errors_count` 熔断计数列，`resolution_status` 取值增加 `'circuit_breaker'`（熔断挂起落盘）。
8. **坏例候选池（2026-09-03，第五阶段 v1）**：`badcase_candidates`（`signal_source`、`conversation_ref` 引用、`business_id`、`suggested_class` 信号先验、`status: 'candidate' | 'confirmed' | 'dismissed' | 'converted'`、`note`）。设计原则：**仓库零原始数据**——只存引用（`thread:{id}` / `approval:{id}` / `fact:{id}`）不存对话/画像原文；保留期 candidate 90 天、dismissed 30 天（`badcase/digest.py` 周期执行）。

### 1.2 多租户物理隔离约束

- **强制租户外键**：除用户全局属性（`users`、`scope = 'global'` 的记忆）外，所有业务数据表（`orders`、`conversations`、`pending_approvals` 等）必须包含 `business_id` 字段。
- **查询与写入防泄漏**：所有 SQLAlchemy 查询必须强制附带 `where(table.business_id == tenant_id)` 条件，禁止无租户限定的裸查。

### 1.3 事务发件箱模式 (Transactional Outbox Pattern)

- 任何高危状态机变更（如批准退款、拒绝申请、修改收货地址）必须在同一个异步事务（`db/session.py` 的 `get_session`）中，原子性地写入 `pending_approvals` 更新与 `approval_outbox_events` 事件生成，彻底杜绝分布式事务丢单。

---

## 2. 迁移与编码准则

1. **类型一致性**：主键和外键统一使用 PostgreSQL `text` 或 `uuid`，时间字段统一使用 `DateTime(timezone=True)` + `server_default=func.now()`。
2. **Alembic 迁移唯一入口**：`bun run db:push`（= `uv run alembic upgrade head`）；schema 变更必须生成新的 Alembic revision（`uv run alembic revision --autogenerate -m "..."`），严禁手改已发布的 versions 文件（与冻结的 TS 基线 schema 保持兼容）。
3. **禁止在模型中写业务逻辑**：`db/models.py` 纯粹承载表结构与关系映射，严禁在 ORM 定义层耦合状态机或 LLM 提示词。
4. **种子数据**：`python -m engine_py.db.seed`（核心）与 `python -m engine_py.db.seed_third_party`（三方）+ `gateway_py.merchant_seed`（商户），通过根脚本 `bun run db:seed` 串联。
