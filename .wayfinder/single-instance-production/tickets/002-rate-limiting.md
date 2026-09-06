---
id: "002"
title: 租户+IP 滑动窗口限流
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
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

## Resolution

`gateway_py/rate_limit.py` 落地 `RateLimitMiddleware`(main.py 注册于 TenantContextMiddleware 之前 → 最内层,复用其解析好的租户口径):ZSET 滑动窗口 + 多键 all-or-nothing Lua 原子判定,双维 = 租户维(护 LLM 账单)+ IP 维(防轮换租户绕过),任一超限即统一 429 `{"success":false,"error":"请求过于频繁，请稍后再试"}` + `Retry-After`。阈值 env:`RATE_LIMIT_WINDOW_SECONDS`、`RATE_LIMIT_{CHAT,SPI}_{TENANT,IP}_MAX`(默认 60/120 与 300/600,IP=规格租户数×2 冗余)、`RATE_LIMIT_KEY_PREFIX`、`RATE_LIMIT_TRUSTED_PROXIES`。

评审修正(相对第一版的三处实质变更):

1. **XFF 采信规则收紧**:v1 取 XFF 首跳(客户端可控)→ 伪造 XFF 即可旋转 IP 桶。现仅当直连 peer ∈ 可信代理名单才解析 XFF,且取**最右非可信跳**;不可信直连一律用真实 peer。
2. **双维判定原子化**:v1 租户维放行后 IP 维拒绝 → 租户维已被计数(拒绝请求进了窗口)。现单 Lua all-or-nothing:任一维超限则所有维不计数。
3. **admin "all" 跳过租户桶**:TenantContext 对无租户态 admin 默认 "all" 为聚合视图,非真实租户;若入桶,多操作员会互相挤兑。

记录的取舍:fail-open(Redis 故障放行并打印错误 —— Redis 与网关 SSE/事件主干同生共死,它挂时业务已不可用,限流不额外阻断);SPI 租户维键取未经 HMAC 验证的 `x-tenant-id` 且限流先于鉴权 —— 伪造 header 可耗尽受害租户 SPI 窗口(IP 维兜底节流单源),硬化路线为 `_authenticate` 通过后补记租户计数;scope 覆盖整个 `/api/chat` 家族(含 GET messages/orders)。

测试:`tests/test_rate_limit.py` 13 用例(合成时钟窗口滑动 / 双维独立 / all-or-nothing / IP 采信 / 429 形状 / 租户与 IP 维独立拦截 / SPI 独立配额先于鉴权 / 伪造 XFF 不可旋转 / 非 scope 路径不受限 / admin "all" 跳过)+ 契约套件 1 用例(冻结路由超载 429 新形状)。全量密封套件 88 passed;`ruff check` 干净;未动引擎 → promptfoo 免跑。live 冒烟(dev:server):3×200 → 第 4 发 429 + `Retry-After: 60`。
