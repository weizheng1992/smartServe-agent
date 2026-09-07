---
id: single-instance-production
title: 单实例真实可运营
type: map
labels: [wayfinder:map]
status: open
created: 2026-09-06
---

## Destination

把仓库里所有 mock、假兜底、静默降级换成真能力,使本平台在**单实例部署**下真实可运营:真实登录、真实限流、真实熔断、评测真实入库、熔断信号真实入池。**本图为执行图(override)**:ticket 直接实现并关闭,地图兼作进度看板;全部子票关闭即到达目的地。

## Notes

- **执行图 override**:与默认"只决策不执行"相反,ticket 是工作单元,领取后直接实现、验证、关闭。
- **验收总纲**(每张票的完成定义):相关 pytest 契约/单测绿;`bun run test:eval` 不回归;动到引擎/生成行为时 `bun run test:prompt:compare` 基线不回归;`uv run ruff check .` 干净。
- **提交纪律**:一张票一组 commit,沿用仓库中文 commit 风格(如 `feat(gateway): ...`、`fix(engine): ...`)。
- **建议技能**:实现类票用 `tdd` 测试先行;受阻塞时用 `diagnosing-bugs`。
- **Tracker 约定**:见 [.wayfinder/README.md](../README.md)。
- 契约冻结(CLAUDE.md 不变量 #6)冻结的是既有 39 条路由的形状;新增路由允许,但必须同批补 pytest 契约测试钉死。

## Decisions so far

- [auth/login 真实登录链路](tickets/001-auth-login.md): bcrypt + JWT(30 天无刷新)+ Redis jti 登出黑名单;静默重校验新增 `/api/auth/me`(UUID 漂移自愈);删 localStorage 假兜底,E2E 切真实凭证。
- [租户+IP 滑动窗口限流](tickets/002-rate-limiting.md): RateLimitMiddleware(ZSET 滑窗 + 多键 all-or-nothing Lua)挂 /api/chat 与 /api/v1/spi;XFF 仅可信反代采信最右跳;admin "all" 跳租户桶;Redis 故障 fail-open。
- [LLM 熔断/指数退避/超时移植](tickets/003-llm-circuit-breaker.md): 全局 CircuitBreaker 单例(TS 1:1)+ 3 次指数退避 + wait_for 超时,挂 `_ResilientChatOpenAI` 公共 invoke/ainvoke 全覆盖;熔断中断的会话落 `resolution_status='llm_circuit_breaker'`(006 数据源);4 节点兜底前置熔断豁免上抛。

## Not yet specified

- **admin 侧发券/改密入口**(001 遗留):目前仅种子账号可登录(其余 `password_hash = NULL` 安全缺省);真实运营需要至少"管理员设密码"端点/入口,等限流(002)落地看清 admin 动作面后再决定立票形状。
- evals 真数据落库后,admin evals 页的展示形态演进(运行对比、失败下钻、趋势)——等真实数据落库、看清形状后再决定是否立票。
- 熔断信号入池后,坏例池是否需要 CLI 之外的最小运营入口——入池跑起来后视消费频率决定(v3.1 全量 admin 坏例池模块仍在不做的范围)。

## Out of scope

- **多实例横向扩容整块**:scheduler 分布式锁/Temporal Schedule、socket.io AsyncRedisManager、灰度脚本——已有 `docs/architecture/multi-instance-deployment.md` 专门设计文档,重画目的地(多实例)时另开新图。
- **Temporal 执行路线启用**(start_workflow 五步,`docs/deployment.md` §3)——部署演进,非运营真实性。
- **其余 Phase 1b 移植项**:多模态 vision、SPI 远程连接器(HMAC/MCP)、takeScreenshot、完整 nlQuery 六件套 + AST 沙箱租户边界注入、KMS/AES-256-GCM——无真实调用方,出现真实需求时回收。
- **Langfuse / OpenTelemetry / APM 整层观测集成**——仅"熔断信号入池"一票进 scope。
- **admin 坏例池模块 + thumbs_down 反馈路由/UI**(v3.1 产品迭代)。
- **四篇 TS 时代架构深潜文档重写**(CHANGELOG 建议单独立案)。
- **multi-tenant.json 挂载进 promptfoo 主配置**——会动已钉死的基线,属评测扩容而非运营真实性。
