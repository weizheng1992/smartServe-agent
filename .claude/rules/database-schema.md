---
description: PostgreSQL SQLAlchemy 数据建模、Alembic 迁移、多租户物理隔离、事务发件箱规范
paths: ["services/engine-py/src/engine_py/db/**/*", "services/engine-py/alembic/**/*"]
---

# 数据库与数据持久层规范 (Database & Schema)

本模块负责 PostgreSQL 物理数据模型定义（`services/engine-py/src/engine_py/db/models.py`，SQLAlchemy）、Alembic 迁移（`services/engine-py/alembic/`）、租户数据物理隔离、事务发件箱事件表。数据库 schema 所有权自 2026-09 起由 Alembic 接管（原 Drizzle `db:push` 已退役）。

## 1. 核心模型与架构规范

### 1.1 核心数据表与职责划分

表名以 `db/models.py` 的 `__tablename__` 为准（2026-09-25 校对）。

1. **会话与消息体系**：
   - `threads`：会话元数据（包含 `business_id`、`user_id`、`status`、`is_takeover` 人工接管标记、`takeover_admin_id`；**注意表名是 `threads` 不是 `conversations`** —— repo 层 `conversation_repo` 操作的物理表即此表）。
   - `messages`：历史轮次物理持久化（`role`、`content`、`cards` 多模态结构化 JSONB）。
2. **多租户与配置**：
   - `tenants`：租户主表;成员 `tenant_members`;技能/引导/SPI 等租户级配置 JSONB 统一在 `tenant_configs`;工具开关在 `tenant_tools`。
3. **客户关系与地址标准化**：
   - `users`：客户档案表（`user_id`、`name`、`email`、`phone`）。
   - `user_addresses`：规范化地址实体表（**表名是 `user_addresses`**;`recipient_name`、`phone`、`province`、`city`、`district`、`detail_address`、`postal_code`）。
4. **电商核心业务表**：
   - `orders`：订单主表;`order_items` 订单商品明细;`products` 商品 + `product_skus` SKU;`logistics_packages`/`logistics_tracks` 物流;`product_reviews` 评价;`after_sale_tickets`/`after_sale_logs` 售后工单。
5. **记忆表（双层画像以 `long_memory_facts.scope` 承载）**：
   - `long_memory_facts`：长期偏好向量表（pgvector 索引;`scope: 'global' | 'tenant'` + `business_id` 实现双层画像物理隔离 —— 没有独立的 persona 表）。
   - `episodic_events`：重大事件记忆表;`task_memory`：挂起任务规划态。
6. **意图与坏例**：
   - `intent_logs`：意图仲裁留痕（candidates 各层提议/winner/arbitration_reason,agent-engine.md §1.3）。
   - `low_confidence_logs`：低置信归档。
   - `badcase_candidates`（2026-09-03）：坏例候选池（`signal_source`、`conversation_ref` 引用、`suggested_class`、`status`、`note`）。**仓库零原始数据** —— 只存引用不存对话/画像原文;保留期 candidate 90 天、dismissed 30 天。
7. **审批与事务发件箱 (HITL & Outbox)**：
   - `pending_approvals`：待人工审核记录（`approval_id`（UUID）、`business_id`、`job_id`、`tool_name`、`status`）。
   - `approval_outbox_events`：事务发件箱事件表（`event_type`、`payload`、`status: 'pending' | 'processing' | 'completed' | 'failed'`、`retry_count`）。
8. **遥测与评测**：
   - `session_metrics`：会话成本遥测;2026-09-03 起新增 `global_transitions_count` / `tool_errors_count` 熔断计数列,`resolution_status` 含 `'circuit_breaker'`。
   - `llm_call_logs`：逐调用 LLM 计量;`agent_jobs`：Temporal/本地作业。
   - `eval_runs`/`eval_results`/`eval_run_records`：promptfoo 真实入库。
9. **Data Agent 与 RBAC（2026-09-19 v4）**：
   - `analytics_trace`：每次问答逐层留痕（`trace_id = tr_<hex12>`,L0/L2/L3/会话/场景包各层）。
   - `analytics_reports`：我的报告服务端持久化（from-result 落库 + CSV 导出）。
   - `query_exemplars`/`intent_exemplars`：L2 范例回放语料。
   - `agent_unanswered`：意图全层未命中池(覆盖增长闭环)。
   - `menus`/`role_menus`/`staff_members`：RBAC 菜单树/角色-菜单分配/员工(商户侧,与 `engine_py/analytics/rbac.py` 配套)。
10. **商户库表(不归本模型所有权)**:`merchant_orders`/`merchant_spus`/promotions/券/核销/审计等真账表在 **`agent_merchant` 独立库**,无 SQLAlchemy 模型 —— gateway 侧经 `merchant_db.py` 裸 SQL,engine 侧经只读 reader(订单域 `order_domain.py`、数据分析 `analytics/engine.py` 按 `target_db` 路由)。

### 1.2 多租户物理隔离约束

- **强制租户外键**：除用户全局属性（`users`、`scope = 'global'` 的记忆）外，所有业务数据表（`orders`、`threads`、`pending_approvals` 等）必须包含 `business_id` 字段。
- **查询与写入防泄漏**：所有 SQLAlchemy 查询必须强制附带 `where(table.business_id == tenant_id)` 条件，禁止无租户限定的裸查。

### 1.3 事务发件箱模式 (Transactional Outbox Pattern)

- 任何高危状态机变更（如批准退款、拒绝申请、修改收货地址）必须在同一个异步事务（`db/session.py` 的 `get_session`）中，原子性地写入 `pending_approvals` 更新与 `approval_outbox_events` 事件生成，彻底杜绝分布式事务丢单。

---

## 2. 迁移与编码准则

1. **类型一致性**：主键和外键统一使用 PostgreSQL `text` 或 `uuid`，时间字段统一使用 `DateTime(timezone=True)` + `server_default=func.now()`。
2. **Alembic 迁移唯一入口**：`bun run db:push`（= `uv run alembic upgrade head`）；schema 变更必须生成新的 Alembic revision（`uv run alembic revision --autogenerate -m "..."`），严禁手改已发布的 versions 文件（与冻结的 TS 基线 schema 保持兼容）。
3. **禁止在模型中写业务逻辑**：`db/models.py` 纯粹承载表结构与关系映射，严禁在 ORM 定义层耦合状态机或 LLM 提示词。
4. **种子数据**：`python -m engine_py.db.seed`（核心）与 `python -m engine_py.db.seed_third_party`（三方）+ `gateway_py.merchant_seed`（商户），通过根脚本 `bun run db:seed` 串联。
