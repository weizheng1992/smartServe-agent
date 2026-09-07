---
id: "003"
title: LLM 熔断/指数退避/超时移植
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
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

## Resolution

新增 `engine_py/llm/resilience.py`,`get_chat_model()` 单例改 `_ResilientChatOpenAI` 在公共 invoke/ainvoke 同时注入遥测与韧性层(与 2026-09-05 遥测同一全覆盖挂点:with_structured_output 组合的模型子步骤同样经公共入口)。

**TS 1:1 语义**(`git show b75fb78~1:packages/engine/src/llm/callLLMWithRetry.ts`):CLOSED/OPEN/HALF_OPEN 状态机(maxFailures=5、cooldown=30s、半开探测失败立即重回 OPEN)、重试循环(3 次、1s 起指数翻倍、穷尽后才 record_failure、任何成功 record_success 清零)、熔断拒绝抛错 + 发布 `${jobId}:status`(`circuit_breaker_open` / `executing` 重试中文话术)。env 全可调:`LLM_CIRCUIT_MAX_FAILURES` / `LLM_CIRCUIT_COOLDOWN_SECONDS` / `LLM_RETRY_MAX_ATTEMPTS` / `LLM_RETRY_INITIAL_DELAY_MS` / `LLM_TIMEOUT_SECONDS`(120s,`asyncio.wait_for` 每次尝试超时中断;≤0 关闭)。**票内待定定案:全局单例**(TS `globalCircuitBreaker` 1:1 —— 熔断对象是上游服务可用性,与租户/模型无关)。

**session_metrics 数据源(006 前置)**:`run_agent` 捕获 `CircuitBreakerOpenError` → 降级道歉回复 + `resolution_status='llm_circuit_breaker'` 落盘。粒度定案:**job 级会话标记**——session_metrics 是会话表,进程级状态翻转(HALF_OPEN 等)无会话归属不落库;006 按"被熔断打断的会话"入池。为此在 4 个节点兜底(triage engine / planner / validator / finish)宽 except 前置 `except CircuitBreakerOpenError: raise` 豁免——上游熔断非节点级可恢复,被兜底吞掉会产出无标记的垃圾回复且降级路径成死代码(Spec 评审发现)。

**评审修正两处实质 bug**:1) 成功路径漏调 `record_success`(计数只增不减,分散失败跨任意时间窗累积误开熔断且永不自愈);2) `_ResilientChatOpenAI` 重试工厂 lambda 内零参 `super()` 无 `__class__` cell → `RuntimeError: no arguments`(先绑定代理再闭包,接线回归测试钉死)。

**记录的取舍**:结构化输出的解析层失败(GLM 围栏 JSON)不经重试——TS 包整个 runner(解析失败重发 LLM 调用),py 侧 triage 已有本地文本自修复兜底(零额外 LLM 调用),模型子步骤的网络级失败仍被本层重试;同步 invoke 为熔断+退避减配版(无超时层、无状态事件),引擎运行时全异步,同步仅供测试/脚本;`_breaker_reject_status` 等小中间函数与 sync/async 循环重复保持 TS 同构,不抽象。

**测试**:`tests/test_llm_resilience.py` 21 用例(状态机合成时钟全覆盖 / 退避序列截获 / 超时中断计数 / 熔断拒绝对模型零触发 / 状态事件发布与无 job 静默 / 接线 super 闭包回归 / 节点豁免上抛 / 降级结果形状)。engine 全量 139 passed;密封套件 88 passed;promptfoo 三套件基线全对齐(47/8/7);ruff 干净。规则文档同步(agent-engine 准则 2、observability §1.2/§1.3 撤销 TODO 挂账)。
