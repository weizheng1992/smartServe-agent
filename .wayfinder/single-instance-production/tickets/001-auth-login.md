---
id: "001"
title: auth/login 真实登录链路
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: ""
status: open
blocked-by: []
blocks: ["004"]
created: 2026-09-06
---

## Question

补齐 `/api/auth/login`,让登录链路真实化。前端 `apps/web/src/pages/LoginPage.tsx:44` 与 `hooks/useAuth.ts:23` 早已在调这个不存在的端点(靠 localStorage 兜底假登录)。

**范围**(建图时已锁定的决策):

- 后端:新增 `/api/auth/login` + 登出;JWT + 密码哈希(bcrypt 或 argon2)、**长过期、不做刷新**。契约冻结只冻既有 39 条,新路由允许但必须同批补 pytest 契约测试钉死。
- 凭证存储:账号由 admin 侧建(不动注册流);建表走 engine-py 的 Alembic 迁移(DB 所有权在 engine)。
- 前端:`useAuth`/`LoginPage` 切真实端点,**删除 localStorage 假登录兜底**;token 本身仍可存 localStorage,删的是"端点不存在时假装成功"的降级路径。
- 依赖该兜底的 E2E(如 `chat-hitl.e2e.ts`)同步改造为真实登录。

**票内待定**(实现 session 自行决策并在 Resolution 记录):静默重校验(`useAuth.ts:12-33`)是校验本地 token 签名/过期,还是顺带新增 `/api/auth/me`;JWT 密钥来源(env)。

**验收**:新路由契约测试绿;`bun run test:eval` 不回归;`bun run test:e2e` 登录路径走真实端点;promptfoo 基线不受影响。
