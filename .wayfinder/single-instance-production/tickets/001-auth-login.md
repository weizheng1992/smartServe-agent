---
id: "001"
title: auth/login 真实登录链路
map: single-instance-production
type: ticket
labels: [wayfinder:task]
mode: AFK
assignee: "weizheng"
status: closed
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

## Resolution

2026-09-06 实现并验收关闭。commits:`41fe4ca`(seed jsonb 独立修复)+ 本票 feat 提交。

**落地**:
- 后端 `routers/auth.py`:`/api/auth/login|logout|me`;bcrypt 凭证(未知邮箱做等时 dummy 校验)、统一 401 文案防账号枚举;JWT HS256(sub/email/jti)默认 30 天无刷新;登出 = Redis jti 黑名单(TTL 至 token 自然过期)。成功载荷走统一信封 `{success, data:{user, token}}`。
- DB:`users.password_hash`(NULL = 不可登录,Alembic 0005,带 inspection 幂等护栏);seed 以 `E2E_ACCOUNT_PASSWORD`(缺省 `agent-all-dev`)幂等覆写种子账号凭证。
- 前端:`LoginPage` 增密码输入;`useAuth` 删 localStorage 假兜底 —— 会话/凭证缺一即清并强制 `/login`;登出先吊销后无条件清本地。E2E 新增 `helpers/auth.ts loginViaUi`,`chat-hitl` 三用例全部走真实登录。

**票内待定裁决**:
- 静默重校验:选**新增 `/api/auth/me`**(非本地验签)——服务端按 email 回查,物理库 re-seed 导致的 UUID 漂移在此自愈;代价是 email 删号重建后旧 token 会绑到新 id,单实例运营期接受。
- JWT 密钥:`AUTH_JWT_SECRET` env(`AUTH_TOKEN_TTL_DAYS` 可调);未注入时用开发缺省并**启动告警**,不静默。

**验收证据**:TestAuth 契约 6/6;全量密封套件 **75 passed** 无回归;chat-hitl E2E chromium **3/3**;ruff/tsc/biome 干净。**合理跳过**:promptfoo compare(未动引擎/生成行为);chat-conversation 套件既有红 = ticket 004 债务(输入框需先点"开启新一轮对话"才可用 + 欢迎语文案漂移),非登录链路问题。

**Review 备注**(双轴 code-review 裁决):admin 侧发券/改密**暂缓**(非种子账号均 `password_hash = NULL` 不可登录,安全缺省;已入地图 fog);`packages/types` 未同步(该包仅 Card/Skill/Tool DTO);0005 手写迁移偏离 autogenerate 流程系为兼容 0001 baseline 的 create_all 幂等,docstring 有载。
