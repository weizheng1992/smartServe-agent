---
id: "003"
title: LLM 熔断/指数退避/超时移植
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: ""
status: open
blocked-by: []
blocks: ["004", "006"]
created: 2026-09-06
---

## Question

把 TS 基线的 LLM 调用韧性三件套移植到 engine-py:熔断器(CircuitBreaker)、指数退避重试、超时控制。挂账证据:`services/engine-py/src/engine_py/llm/chat.py:17`、`run_agent.py:13-14`、`.claude/rules/agent-engine.md` §2 准则 2。TS 参考实现在退役的 `callLLMWithRetry.ts`(git 历史可考,建议 `git log --all --oneline -- '**/callLLMWithRetry*'` 找回)。

**范围**:

- 作用于 `llm/chat.py` 的 LLM 调用路径(含 `with_structured_output` 构造——注意 callbacks 不穿透的已知坑,见 memory)。
- 熔断状态翻转要落 `session_metrics`(遥测已有,2026-09-05 补齐)——这是 ticket 006(熔断信号入池)的数据源。
- 退避参数与熔断阈值(env 可调);超时覆盖 triage/planner 等全部 LLM 调用点。

**票内待定**:熔断粒度(全局单例 vs 按模型/按租户);TS 基线若为全局则 1:1 保持。

**验收**:单测覆盖熔断开/半开/合、退避序列、超时中断;`bun run test:eval` 不回归;`bun run test:prompt:compare` 基线不回归(韧性层不应改变正常路径输出);ruff 干净。
