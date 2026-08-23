---
description: 结构化日志、Langfuse 链路追踪、Token 计费遥测与可观测性规范
paths: ["packages/observability/**/*"]
---

# 可观测性与遥测规范 (Observability & Telemetry)

本工作区负责整个 Monorepo 的结构化日志记录（Pino）、Langfuse 分布式链路追踪、Token 消耗计量与业务质量大盘指标统计。

## 1. 核心架构

- **结构化日志 (`logger.ts`)**：基于 Pino 构建的高性能异步 JSON 日志输出，自动附带 `threadId`、`jobId`、`tenantId` 与时间戳元数据。
- **分布式追踪 (`langfuseClient.ts`)**：集成 Langfuse SDK，跟踪 Agent 决策图各个节点（Triage、Planner、Executor、Validator）的执行 Span 与耗时。
- **Token 计量与成本统计 (`metrics.ts`)**：
  - 自动累加并计算 Prompt Tokens 与 Completion Tokens。
  - 基于模型单价（如 Claude / Gemini 费率）动态折算单次会话的 USD/CNY 成本。
  - 统计自动决议率（Autopilot Resolution Ratio）与人工升级率（Escalation Ratio）。

## 2. 开发准则

- **日志脱敏防线**：在记录包含用户输入或工具出参的日志时，严禁打印未脱敏的 PII 信息（密码、真实身份证、完整银行卡号等）。
- **统一客户端引用**：业务模块应统一通过 `@agent-all/observability` 引入 `logger` 与指标收集方法，严禁在生产代码中使用裸 `console.log`。
