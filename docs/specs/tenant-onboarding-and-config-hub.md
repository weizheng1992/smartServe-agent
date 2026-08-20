# 📋 SaaS 商户自主入驻与配置中心技术规格书 (Technical Specification)

**状态:** Ready for Implementation  
**版本:** v1.0.0  
**关联决策地图:** [.scratch/wayfinder/map.md](../../.scratch/wayfinder/map.md)

---

## 1. 架构总览 (Architecture Overview)

本系统为智能客服平台提供 **SaaS 商户自主入驻、知识库自助导入、OpenAPI 动态工具注册、密钥安全管理与提示词沙箱调试** 的完整自闭环技术体系。

```text
+----------------------------------------------------------------------------------------------------+
|                                    SaaS 商户管理控制台 (apps/admin)                                  |
|                                                                                                    |
|  [商户入驻 & IAM]     [Contextual RAG]         [动态工具注册]       [KMS 密钥中心]     [Prompt 沙箱] |
|   Owner/Admin/Agent     多格式文档解析切片       OpenAPI 3.0 / Hook   AES-256-GCM       左右双栏调试  |
+---------+--------------------+------------------------+-------------------+----------------+-------+
          |                    |                        |                   |                |
          v                    v                        v                   v                v
+---------+--------------------+------------------------+-------------------+----------------+-------+
|  多租户数据与安全边界           Temporal 异步流水线       动态 Tool 运行时沙箱   JIT 即时解密中间件  LangGraph 图引擎 |
|  Postgres (Drizzle)           IngestDocumentWorkflow   SSRF 防御 & 8s 超时    Pino/Trace 脱敏   Draft/Publish  |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. 核心架构设计与决策规范 (Core Decisions)

### 2.1 租户组织模型与数据隔离边界 (Tenant IAM & Data Scoping)

1. **单层商户模型 (Tenant = Brand)**:
   - 租户根标识统一采用 `businessId` 命名空间（如 `nike`, `anker`），100% 契合现有引擎状态机。
   - `tenants` 表管理企业主体与套餐等级 (`planTier`: `free` | `pro` | `enterprise`)。
   - `tenant_members` 实现 **Owner / Admin / Agent** 三级 RBAC 权限体系。
2. **强制行级数据隔离**:
   - 所有数据表（`threads`, `orders`, `products`, `rag_documents`, `session_metrics`, `tenant_tools`, `pending_approvals`）均包含 `business_id` 索引字段。
   - API 中间件与 Drizzle ORM 层强制拼装 `eq(table.businessId, activeBusinessId)` 过滤谓词。

### 2.2 知识库多格式文档切片与 Contextual RAG 流水线

1. **解析库选型**:
   - PDF 采用纯 TypeScript 的 `unpdf`；Word 文档采用纯 JS 的 `mammoth`；Markdown/TXT 采用 `marked`。
2. **切片与情境摘要规范 (Anthropic Contextual Retrieval)**:
   - 递归段落切片：Chunk 目标大小 **~600 tokens**，重叠 **100 tokens**。
   - 上下文增益摘要：调用 LLM 为每个切片生成 50-80 词情境摘要，拼接写入 `rag_documents.contextual_summary`。
3. **Temporal 异步工作流**:
   - `IngestDocumentWorkflow` 驱动 `ParseFileActivity` -> `ChunkTextActivity` -> `GenerateContextualSummariesActivity` -> `GenerateEmbeddingsActivity` -> `BulkInsertWithVectorValidationActivity`。

### 2.3 OpenAPI 3.0 与 Webhook 动态工具注册与沙箱

1. **动态工具生成**:
   - 采用 `@scalar/openapi-parser` 解析 OpenAPI 3.0 规范，自动将 Parameter/RequestBody 映射为 Zod Schema。
   - 动态装载为 `packages/tools` 中的 `DynamicStructuredTool`。
2. **运行时安全沙箱**:
   - **SSRF 拦截**: DNS 预解析 + 硬拦截私网及元数据网段 (`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.169.254`) 与跳转检测。
   - **超时控制**: 单次 HTTP 请求设置 `AbortSignal.timeout(8000)`（8秒上限）。
   - **PII 敏感数据清洗**: 全链路调用 `packages/tools/src/scrubber.ts`。
3. **HITL 审批对接**:
   - 显式声明 `x-requires-approval: true` 或匹配 `POST/PUT/DELETE` 路径的工具，`executor.node.ts` 自动拦截并派发至 `pendingApprovals` 审批流。

### 2.4 商户专属 API 凭证安全存储 (KMS & JIT Injection)

1. **AES-256-GCM 对称加密**:
   - 密文格式：`iv:authTag:ciphertext`（12 字节 IV + 16 字节 AuthTag，统一 Hex 编码）。
2. **HKDF 租户专属密钥派生**:
   - 基于主密钥 `ENCRYPTION_MASTER_KEY` + `tenantId` 盐值，通过 `crypto.hkdfSync` 派生独立 32 字节 Key。
3. **JIT 即时注入与全链路脱敏**:
   - 仅在发起 HTTP 请求前毫秒级解密注入 Header，不在 State 滞留。
   - Pino 日志、Langfuse Span 及前端 SSE 事件流全量脱敏拦截。

### 2.5 提示词沙箱（Prompt Playground）与发布生命周期

1. **左右双分栏交互架构**:
   - 左侧：品牌人设、System Prompt 模板、SOP 规则、模型参数（温度、Top-P）与动态工具开关。
   - 右侧：实时沙箱对话 + 透视大盘（Triage 意图分类、Contextual RAG 命中文档、工具调用耗时与 Token 统计）。
2. **Draft -> Publish 双状态管理**:
   - 草稿（Draft）配置仅在沙箱生效，不影响线上真实客服。
   - 一键发布（Publish to Live）原子更新并刷新缓存，线上即刻无缝生效。

---

## 3. 实施拆解清单 (Implementation Breakdown)

- **Phase 1 (DB & IAM)**: Drizzle Schema 扩充 (`tenants`, `tenant_members`, `tenant_configs`, `tenant_tools`) 与租户隔离中间件。
- **Phase 2 (RAG & Temporal)**: 多格式解析与 `IngestDocumentWorkflow` 异步摄入流水线开发。
- **Phase 3 (Tools & Sandbox)**: OpenAPI 3.0 解析器、动态 Tool 注册中心与 SSRF 安全沙箱。
- **Phase 4 (KMS & Crypto)**: AES-256-GCM 加密工具包与 JIT Header 注入中间件。
- **Phase 5 (Admin UI & Playground)**: `apps/admin` 商户配置中心界面与实时调试 Prompt Playground。
