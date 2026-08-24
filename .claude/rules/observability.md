---
description: 结构化多租户日志、Langfuse 链路追踪、SaaS 计费遥测与自动驾驶指标规范
paths: ["packages/observability/**/*"]
---

# 观测性、遥测追踪与成本账单规范 (Observability & Telemetry)

本工作区负责全系统的观测基础设施，包括 Pino 结构化日志、Langfuse 大模型链路追踪、SaaS 动态 Token 计费模型与智能体执行度量指标。

## 1. 核心体系与实现规范

### 1.1 结构化多租户日志 (`logger.ts`)

- **上下文标记强制注入**：所有日志必须显式绑定上下文元数据（`tenantId`, `threadId`, `nodeName`, `stepId`, `requestId`）。
- **敏感信息脱敏 (PII Scrubbing)**：严格过滤日志中出现的手机号、明文密钥、用户身份证与支付凭证。

### 1.2 Langfuse 大模型链路追踪

- **端到端 Trace 上报**：从 `triage` 意图识别、`planner` 步骤生成到子工具执行，全链路打通 Langfuse Trace 与 Generation Span。
- **Prompt 版本治理与 Metadata**：记录模型版本、Temperature、Prompt 模板版本及输入输出 Token 计数。

### 1.3 SaaS 计费模型与自动驾驶遥测 (`telemetryService.ts`)

- **动态成本核算**：按模型单价（Input / Output / Embedding）精确计算每次会话的 USD 成本并聚合落盘。
- **自动驾驶解决率 (Autopilot Resolution Ratio)**：
  - 统计无需人工接管直接在智能体生命周期内闭环完成的会话比例。
  - 实时监控低置信度回退率、HITL 触发率与平均执行轮次（Step Count）。

---

## 2. 编码与维护准则

1. **异步非阻塞**：日志与追踪上报严禁以阻塞方式介入主状态机执行关键路径。
2. **容灾降级机制**：当 Langfuse 远端服务异常或网络超时时，日志与遥测服务必须静默降级至本地控制台输出，不得阻断业务。
