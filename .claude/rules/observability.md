---
description: 结构化多租户日志、遥测追踪、SaaS 计费与自动驾驶指标规范
paths: ["services/engine-py/src/engine_py/run_agent.py", "services/engine-py/src/engine_py/llm/**/*", "services/gateway-py/src/gateway_py/main.py"]
---

# 观测性、遥测追踪与成本账单规范 (Observability & Telemetry)

后端观测能力随 Python 迁移分散落在引擎各节点中（原 `packages/observability` 已退役）：结构化上下文日志（print + 前缀标记）、LangSmith 遥测反馈、SaaS 动态 Token 计费模型（`session_metrics` 物理表）与智能体执行度量指标。

## 1. 核心体系与实现规范

### 1.1 结构化多租户日志

- **上下文标记强制注入**：所有日志必须显式携带上下文元数据（`tenantId`, `threadId`, `nodeName`, `stepId`, `requestId`），统一 `[模块] 前缀 + 中文描述` 格式（如 `[SaaS Config Engine]`, `[DB]`）。
- **敏感信息脱敏 (PII Scrubbing)**：严格过滤日志中出现的手机号、明文密钥、用户身份证与支付凭证。

### 1.2 LLM 链路追踪

- **端到端 Trace 上报**：从 `triage` 意图识别、`planner` 步骤生成到子工具执行的链路遥测；当前实现为 LangSmith feedback 上报（`run_agent.py`）。
- **Prompt 版本治理与 Metadata**：记录模型版本、Prompt 模板版本及输入输出 Token 计数（`llm/chat.py` 承载统一入口）。
- **逐调用遥测落盘（2026-09-05 起）**：`llm/telemetry.py` 的 `LlmCallTelemetryHandler` 把每次对话模型调用的真实 `usage_metadata` / 延迟 / 模型名 / 归因（`thread_id`、`business_id`、`langgraph_node`）写入 `llm_call_logs`；挂点为 `_TelemetryChatOpenAI` 覆写公共 `invoke/ainvoke` 统一注入 `config.callbacks`——构造期 callbacks 不随 `with_structured_output` 组合传播（实测漏采 triage）。`run_agent` 聚合前 `drain_llm_call_writes` 收口，`session_metrics.total_tokens` 取 `take_thread_token_total` 真值；`/api/logs` 的 `llm_call` 类型逐字段透传该表。已知边界：结构化输出在 SDK 侧解析抛错（GLM 围栏 JSON）的调用不触发 `on_llm_end`，此类消耗只经 fallback 的补救 `ainvoke` 落盘。
- **迁移缺口**：TS 侧 Langfuse 深度集成与 `callLLMWithRetry` 的熔断/退避为未完成 TODO，补齐前禁止删除现有 print 降级路径。

### 1.3 SaaS 计费模型与自动驾驶遥测

- **动态成本核算**：按模型单价精确计算每次会话的 USD 成本（$0.15/M tokens 换算）并聚合落盘至 `session_metrics`。
- **自动驾驶解决率 (Autopilot Resolution Ratio)**：
  - 统计无需人工接管直接在智能体生命周期内闭环完成的会话比例。
  - 实时监控低置信度回退率、HITL 触发率与平均执行轮次（Step Count）。
- **熔断落盘（2026-09-03 起）**：会话命中熔断（全局转移 ≥10 次或工具错误 ≥3 次，阈值见 `graph/build_graph.py`）时，`run_agent` 以 `resolution_status='circuit_breaker'` 落盘 `session_metrics` 并同步计入 `global_transitions_count` / `tool_errors_count`；`/api/logs` 的 `rawDetail` 透出这两个计数，坏例候选池据此单独立案。

---

## 2. 编码与维护准则

1. **异步非阻塞**：日志与追踪上报严禁以阻塞方式介入主状态机执行关键路径。
2. **容灾降级机制**：当 LangSmith 远端服务异常或网络超时时，遥测必须静默降级至本地控制台输出，不得阻断业务。
3. **失败静默但不吞错**：遥测/配置加载的 try/except 分支必须 print 错误上下文（含异常信息），严禁空 except。
