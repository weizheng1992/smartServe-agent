---
id: "002"
title: 租户+IP 滑动窗口限流
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: ""
status: open
blocked-by: []
blocks: []
created: 2026-09-06
---

## Question

在 gateway-py 落地限流/防刷。TS 时代规格 `docs/specs/server-gateway-hardening-and-scaling.md` Problem 3 / Solution 3 承诺了租户+IP 滑动窗口限流,Python 侧 grep `throttl|rate.?limit|限流` 零命中。

**范围**:

- 基于 Redis 的滑动窗口(租户 ID + IP 两维),超限返回 429;中间件形态挂在聊天 SSE 与 SPI v1 等高频入口。
- 阈值配置从 env 起步(如 `RATE_LIMIT_*`),不改 39 条冻结路由的响应形状(限流只在超载时介入)。

**验收**:限流单测(窗口滑动、超限 429、维度独立计数);`bun run test:eval` 不回归;`uv run ruff check .` 干净。
