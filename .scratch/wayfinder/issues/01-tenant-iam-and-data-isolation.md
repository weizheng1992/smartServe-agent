# TICKET-01: 租户组织模型与多租户数据隔离边界设计

**Label:** `wayfinder:grilling` (HITL)  
**Parent Map:** [Wayfinder Map](../map.md)  
**Assignee:** zwei24  
**Status:** Closed

---

## Question

在现有 PostgreSQL + Drizzle ORM 单库架构下，商户自主入驻后的组织模型（Organization / Tenant / Merchant）、品牌维度（Business / Brand）、用户与角色（Owner / Admin / Agent）实体关系应如何设计？

对于所有业务数据表（`orders`, `messages`, `threads`, `rag_documents`, `pending_approvals`, `tools`），如何规范行级租户隔离（Scoping Strategy）与外键约束，以确保 100% 杜绝多租户跨商户越权与数据泄露？

---

## Resolution Decisions

### 1. 实体层级模型：单层商户模型 (Tenant = Brand)

- **概念对齐**：每家自主入驻的商户公司作为一个独立的 Tenant（租户），其全局唯一标识 `businessId`（如 `nike`, `anker`, `ecommerce`）即代表其品牌命名空间。与现有引擎状态机与表结构的 `businessId` 保持 100% 兼容。
- **核心数据表设计**:
  - `tenants`: `id` (UUID PK), `businessId` (text UNIQUE), `name` (text), `planTier` (text: 'free'|'pro'|'enterprise'), `status` (text: 'active'|'suspended'), `createdAt` (timestamp).
  - `tenant_members`: `id` (UUID PK), `tenantId` (UUID FK -> `tenants.id`), `userId` (UUID FK -> `users.id`), `role` (text: 'owner'|'admin'|'agent'), `createdAt` (timestamp).
  - `tenant_configs`: `id` (UUID PK), `businessId` (text UNIQUE), `systemPrompt` (text), `welcomeMessage` (text), `temperature` (real), `status` (text: 'draft'|'published'), `updatedAt` (timestamp).

### 2. 三级 RBAC 权限边界

| 角色 (Role) | 权限边界与职能                                                                                               |
| :---------- | :----------------------------------------------------------------------------------------------------------- |
| **Owner**   | 拥有商户公司最高控制权：账号注销、成员邀请与角色分配、套餐订阅与账单、系统级配置全量发布。                   |
| **Admin**   | 知识库与能力管理员：上传/更新 SOP 文档、配置 OpenAPI 动态工具与 API 密钥、审批 HITL 高危退款与改地址工单。   |
| **Agent**   | 一线人工客服坐席：实时接管用户转人工会话（IM 坐席台）、查看订单与工单详情，无权更改系统配置或解密 API 密钥。 |

### 3. 行级隔离与外键约束规范 (Data Scoping Strategy)

1. **强制租户外键关联**：所有业务实体表（`threads`, `orders`, `products`, `rag_documents`, `session_metrics`, `tenant_tools`, `pending_approvals`）均保留 `business_id` 作为非空索引字段。
2. **中间件与 Query 作用域拦截**：
   - Next.js API Middleware 从用户 Session 提取当前激活的 `activeBusinessId` 与 `role`，挂载至请求上下文。
   - 所有 Drizzle ORM 查询必须强行附加 `eq(table.businessId, activeBusinessId)` 谓词，杜绝一切跨商户数据越权与嗅探。
