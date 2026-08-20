# Wayfinder Map: SaaS 商户自主入驻与配置中心 (Self-Service Tenant Onboarding & Config Hub)

**Label:** `wayfinder:map`  
**Status:** Completed (Ready for `/to-spec`)  
**Owner:** zwei24

---

## Destination

输出一份经过全面决策锁定的《SaaS 商户自主入驻与配置中心技术规格书 (Technical Specification)》，包含多租户组织数据模型、多格式文档 Contextual RAG 摄入流水线、OpenAPI 动态工具注册与安全执行沙箱、商户密钥 KMS 加密以及品牌提示词沙箱，能够直接指导后续 Monorepo 工单实施与代码落地。

---

## Notes

- **相关模块**: `apps/admin`, `apps/web`, `packages/db`, `packages/engine`, `packages/tools`, `packages/business-configs`
- **核心依赖技术**: Drizzle ORM (PostgreSQL), LangGraph StateGraph, Temporal Workflows, Contextual RAG Embedding, OpenAPI 3.0
- **关键原则**:
  1. 严格的多租户物理与逻辑安全隔离（Zero cross-tenant leakage）；
  2. 最小化模型幻觉，强依赖物理数据接地（Data Grounding）；
  3. 异步高吞吐的任务摄入与工具执行沙箱机制。

---

## Decisions so far

- [TICKET-01: 租户组织模型与多租户数据隔离边界设计](issues/01-tenant-iam-and-data-isolation.md) — 确立单层商户模型 (`businessId` 命名空间)、Owner/Admin/Agent 三级 RBAC 权限与基于 Drizzle 的强制行级数据隔离。
- [TICKET-02: 知识库多格式文档切片与 Contextual Retrieval 异步摄入流水线](issues/02-knowledge-ingestion-pipeline.md) — 选定 `unpdf`/`mammoth` 多格式解析、~600 token 递归边界切片与 Temporal 异步 Contextual 摘要提取流水线。
- [TICKET-03: OpenAPI 3.0 与 Webhook 动态工具注册与安全沙箱机制](issues/03-openapi-dynamic-tools.md) — 确立 `@scalar/openapi-parser` 动态 Tool 生成、SSRF 私网硬拦截网络沙箱与 `x-requires-approval` 自动 HITL 审批挂载方案。
- [TICKET-04: 商户专属 API 凭据安全加密存储（AES-256-GCM / KMS）方案](issues/04-tenant-secrets-kms-storage.md) — 确立基于 HKDF 租户派生密钥的 AES-256-GCM (`iv:authTag:ciphertext`) 加密落盘与运行时 JIT 即时解密脱敏注入。
- [TICKET-05: 提示词沙箱（Prompt Playground）与品牌心智配置交互设计](issues/05-prompt-playground-ux.md) — 确立左右双分栏配置工作台（左侧人设/提示词/工具挂载，右侧实时沙箱与决策大盘透视）与 Draft -> Publish 双状态生效机制。

---

## Frontier (Takeable Now)

_(所有决策工单已全量敲定，前沿迷雾已彻底拨开)_

---

## Blocked Tickets

_(无)_

---

## Not yet specified

_(所有核心决策已锁定)_

---

## Out of scope

- **全渠道第三方即时通讯网关物理接入（微信/飞书/WhatsApp）**: 本阶段专注在商户自主入驻、知识库、工具与配置中心，多渠道适配器作为后续独立工程规划。
- **自建 LLM 大模型微调（Fine-tuning）系统**: 本系统完全基于 Prompt Engineering、动态 Tools 与 Contextual RAG，不涉及底层权重训练与微调。
