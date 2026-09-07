---
id: "006"
title: 熔断信号入坏例池
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
blocked-by: ["003"]
blocks: []
created: 2026-09-06
---

## Question

把熔断信号接进坏例池。现状:`badcase/pool.py:15,23` 已定义 `SOURCE_CIRCUIT_BREAKER` 及其先验,但全仓无调用点写入(`.claude/rules/agent-engine.md` §1.8:"熔断信号 run_agent 落盘,暂未入池")。

**前置**:依赖 ticket 003——熔断器不存在则无信号可写。

**范围**:

- 在熔断状态翻转处(ticket 003 落地的状态机)挂写入点,调用 badcase pool 的既有入池 API(参照 `gatekeeper.py` 两个挂点、`crud.py` 一个挂点的用法)。
- scheduler 的坏例摘要(6h 周期任务)确认能消费到新信号源。

**验收**:单测证明熔断打开→信号入池→摘要包含;既有 badcase pool 测试不回归;ruff 干净。

## Resolution

`run_agent` metrics 收口处挂 `record_badcase_signal(SOURCE_CIRCUIT_BREAKER, ...)`,覆盖两路熔断:`llm_breaker_fired`(上游 LLM 熔断,备注"上游 LLM 熔断(OPEN)拦截")与图级 `breaker_fired`(备注携带全局转移/工具错误计数);先验 `suspected_defect`,与 session_metrics 熔断落盘同位。

**挂点定案(票面"状态翻转处"的修正)**:落在 run_agent 会话收口而非 resilience.py 状态机翻转处 —— ① 图级熔断无状态机(结果计数判定);② LLM 熔断器进程全局,翻转可能发生在无会话归属的后台调用,而池以会话为评审单位;③ 票面 Question 自述债务即"熔断信号 run_agent 落盘,暂未入池"。Spec 评审认定该偏离忠实于意图。残留盲区(接受):非 run_agent 链路的 LLM 调用熔断不产生信号 —— 会话级池的固有口径。

**Spec 评审修正**:OPEN 窗口内同一会话每回合重试都会入池(用户重试风暴刷行)—— `record_badcase_signal` 新增 opt-in `dedupe=True` 幂等护栏(同 source+ref 已有 candidate 则跳过并返回既有 ID),对齐 gatekeeper 转人工挂点"重复呼叫不重复入池"语义;既有三个调用点不受影响(默认 False)。

**摘要消费**:`run_badcase_digest` 按 signal_source 分组通用收纳,新信号源零改动自动进 6h 摘要,测试钉死。

**记录的取舍**:入池挂点位于遥测 try 尾部,SessionMetric 落盘先抛则会漏信号 —— 该场景 DB 本身已故障,入池(同库)大概率同败,不为它加独立 try;入池采用 await(与 gatekeeper 挂点一致,信号是引用非遥测,不追求 fire-and-forget)。

**测试**:`tests/test_circuit_breaker_badcase.py` 5 用例,密封 PG 驱动 run_agent 真实主流程(伪图注入 CircuitBreakerOpenError 模拟 003 豁免上抛链路;替身记忆避开 embedding/LLM;输入 ≤3 字符跳过三路检索):LLM 熔断入池+先验+落盘、图级熔断入池+备注、去重幂等、摘要消费、正常会话不入池负例。engine 全量 144 passed;密封套件 88 passed;promptfoo 三套件基线对齐(47/8/7);ruff 干净。规则文档 agent-engine §1.8 撤销"暂未入池"挂账。commit 844302d。
