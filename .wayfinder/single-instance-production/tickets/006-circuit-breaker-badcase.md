---
id: "006"
title: 熔断信号入坏例池
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: in_progress
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
