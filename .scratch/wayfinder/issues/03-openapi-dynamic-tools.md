# TICKET-03: OpenAPI 3.0 与 Webhook 动态工具注册与安全沙箱机制

**Label:** `wayfinder:research` (AFK)  
**Parent Map:** [Wayfinder Map](../map.md)  
**Assignee:** Subagent (Completed)  
**Status:** Closed

---

## Question

在多租户智能客服平台中，商户需要接入自定义业务系统（如私有 ERP、自研电商系统的查单/改地址/查库存接口）。如何支持商户直接导入 OpenAPI 3.0 (Swagger) JSON 或配置 HTTP Webhook，并将其动态注册为 LangGraph 决策图可调度的工具？

---

## Resolution Findings

1. **OpenAPI 3.0 动态解析与 Zod 生成**:
   - 采用 `@scalar/openapi-parser` 解析 JSON/YAML，展开 `$ref` 引用；
   - 动态映射 JSON Schema 到 `z.object()` 运行时校验结构，注册到 `packages/tools` 动态工具注册表。

2. **HTTP 运行时沙箱防护 (SSRF / 超时 / 脱敏)**:
   - **SSRF 拦截**: DNS 预解析 + 硬拦截私网网段（`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.169.254`）与多跳重定向校验；
   - **超时与熔断**: `AbortSignal.timeout(8000)`（8秒上限）；
   - **PII 脱敏**: 请求/响应经由 `packages/tools/src/scrubber.ts` 统一清洗。

3. **HITL 审批流自动挂载**:
   - 显式声明 `x-requires-approval: true` 或 HTTP `POST/PUT/DELETE` 关键路径自动打标 `requiresApproval = true`；
   - `executor.node.ts` 自动拦截并推入 `pendingApprovals` 审批流。
