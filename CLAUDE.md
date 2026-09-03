# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本仓库中工作时提供指导。

## 1. 开发命令

### 1.1 启动服务

- **启动全部服务:** `bun run dev:all`(前端走 turbo,Python 服务单独启动)
- **启动 Web 应用:** `bun run dev:web`(端口 3000,Vite 6 SPA)
- **启动 Admin 管控台:** `bun run dev:admin`(端口 3001,Vite 6 SPA)
- **启动 FastAPI 网关:** `bun run dev:server`(端口 4000,`uv run uvicorn gateway_py.main:app --reload`)
- **启动独立商户应用:** `bun run dev:merchant`(端口 3005,Next.js;`/api/*` 与 `/spi/*` 代理至 gateway-py)
- **启动 Temporal Worker:** `bun run worker`(`uv run python -m engine_py.temporal.worker`,任务队列 `agent-tasks-py`)

### 1.2 构建、Lint 与格式化

- **构建前端工作区:** `bun run build`
- **Lint 全仓:** `bun run lint`
- **Biome 检查与格式化:** `bun run biome:check` / `bun run biome:format`
- **Python lint(ruff):** `cd services/engine-py && uv run ruff check .`(gateway-py 同理)

### 1.3 测试与评测

- **运行网关契约测试:** `bun run test:eval`(pytest 于 `services/gateway-py`,密封 testcontainers PG+Redis)
- **运行单个测试文件:** `cd services/gateway-py && uv run pytest tests/test_http_routes_contract.py`
- **运行 Playwright E2E 测试:** `bun run test:e2e`
- **运行 Promptfoo 评测:** `bun run test:prompt`(Classify)/ `bun run test:prompt:planner`(Planner)
- **钉死 / 对比 Promptfoo 基线:** `bun run test:prompt:pin` / `bun run test:prompt:compare`

### 1.4 数据库与基础设施

- **启动核心 Docker 服务:** `bun run docker:up`(PostgreSQL + Redis)
- **启动 Temporal 集群:** `bun run docker:temporal`
- **停止 Docker 服务:** `bun run docker:down`
- **应用 Schema 迁移:** `bun run db:push`(Alembic `upgrade head`,在 `services/engine-py` 中执行)
- **数据库播种:** `bun run db:seed`(engine 播种 + 第三方播种 + 商户播种)

---

## 2. 高层架构地图

Monorepo 由 Turborepo + Bun workspaces(前端)与 uv workspace(Python 服务)共同管理:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                      前端应用 (apps/, TypeScript)                      │
│  - apps/web:      Vite 6 + React 19 客户端聊天 SPA(SSE、卡片)         │
│  - apps/admin:    Vite 6 + React 19 SaaS 管控台(10 大模块)           │
│  - apps/merchant: 独立商户门户(Next.js;代理至 Python 网关)           │
└───────────────────────────┬────────────────────────────────────────────┘
                            │ HTTP / SSE / socket.io
                            ▼
┌────────────────────────────────────────────────────────────────────────┐
│              API 网关 (services/gateway-py,Python/FastAPI)             │
│  - 39 条契约冻结路由:tenants、skills、approvals、聊天 SSE、           │
│    conversations、RAG 文档、personas、guardrails、billing、logs、      │
│    商户 store/admin、SPI v1(HMAC 签名)                                │
│  - 实时:SSE(Redis Streams 事件源)+ python-socketio                  │
│    人工接管房间(joined_room / peer_joined / typing / ...)            │
└───────────────────────────┬────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────────┐
│           决策引擎 (services/engine-py,Python/LangGraph)               │
│  LangGraph DAG:triage ──→ planner ──→ merge ──→ 循环 [exec ⇄ val]     │
│  - Skills 管道:BaseSkill、SOP 规则、租户配置覆写                      │
│  - 记忆:四象限记忆(Short/Long/Episodic/Task)+ 双层画像               │
│  - Contextual RAG:上下文增强切片 + 租户过滤检索                       │
│  - HITL:ApprovalGatekeeper(事务发件箱 + 同步 Fast-Path 恢复,        │
│    对账 Worker 未启动,见不变量 #3)                                   │
│  - 编排:Temporal 工作流(队列 agent-tasks-py)+ 本地仿真回退;        │
│    shadow-harness 对冻结 TS 基线做 diff/replay                        │
│  - 事件主干:Redis Streams(seq + XADD maxlen per job)                │
│  - DB 所有权:SQLAlchemy 模型 + Alembic 迁移                           │
└──────────────┬─────────────────────┬───────────────────────────────────┘
               │                     │
               ▼                     ▼
┌──────────────────────────┐ ┌──────────────────────────────────────────┐
│  packages/ui             │ │  packages/types                          │
│  - 零依赖原子组件        │ │  - 冻结的前端契约类型(zod)              │
│  - 富卡片家族            │ │  - web + admin + merchant 共享的          │
│  - SVG 图标库            │ │    Card / Skill / Tool DTO(仅 TS)       │
└──────────────────────────┘ └──────────────────────────────────────────┘
```

后端历史:原始 TypeScript 后端(`apps/server` NestJS 网关、`packages/{engine,tools,db,business-configs,observability}`)在 1:1 Python 移植(2026-09)后退役。`packages/types` 作为冻结的前端契约保留;退役 TS 代码的行为由 `services/gateway-py/tests/` 的 pytest 契约套件钉死。

---

## 3. 核心架构不变量

1. **多租户物理与逻辑隔离**:
   - 每一条数据库查询与工具执行必须携带 `tenantId` / `businessId`。
   - 双层画像记忆严格区分 `scope = 'global'`(通用用户特征)与 `scope = 'tenant'`(品牌专属偏好)。
2. **Skills 与工具执行管道**:
   - 遵循 `Planner ➔ Skill ➔ SPI/MCP Connector ➔ Service/DB`。
   - 业务动作继承 `BaseSkill`,带声明式 SOP 校验、生命周期钩子(`pre_execute`、`execute`、`post_execute`)与租户配置覆写。
   - 底层外部集成使用 HMAC-SHA256 签名、防重放与带 SSRF 防护的连接器。
3. **HITL 审批与事务发件箱**:
   - 敏感动作(超阈值退款、地址修改)挂起执行并写入 `pending_approvals`。
   - 审批状态变更与 `approval_outbox_events` 事件在**同一数据库事务**中原子提交。
   - 恢复机制(2026-09-03 起):审批通过/驳回/取消后,由 gatekeeper 的**同步 Fast-Path** 以确定性 JobId `job_resume_${approvalId}` 派发 `run_agent` 恢复执行,派发成功即标记事件 `completed`;Fast-Path 失败遗留的 `pending` 事件由 `approvals/outbox_worker.py` 对账补偿(`FOR UPDATE SKIP LOCKED`,10s 年龄阈值避开竞争,`processing` 停滞 >5min 重入队)。
   - 对账补偿与坏例池摘要等周期任务由 `engine_py/scheduler.py` 统一调度,随 Temporal worker 入口启动(Temporal 离线时仍独立运行)。**单实例假设**,多实例部署前需分布式锁或迁移 Temporal Schedule;`ENGINE_SCHEDULER_ENABLED=0` 可整体关闭。
4. **参数化 AST SQL 沙箱**:
   - NL2SQL 经 AST 解析器检查,强制仅 `SELECT`、注入租户边界、追加 `LIMIT 50`,并在只读事务超时控制下执行。
5. **零依赖共享 UI**:
   - `apps/web` 与 `apps/admin` 使用 `@agent-all/ui` + Tailwind CSS,不得引入重型外部组件框架。
6. **契约冻结**:
   - 39 条 HTTP 路由、SSE 线格式与 socket.io 事件冻结于 TS 基线;pytest 契约套件(`services/gateway-py/tests/`)是事实标准。

---

## 4. 工作区规则索引

详细领域规则与编码规范按模块组织于 `.claude/rules/`:

- `agent-engine.md`:LangGraph 拓扑、Skills 注册表、四象限记忆、Contextual RAG、Temporal 工作流。
- `database-schema.md`:SQLAlchemy 模型、Alembic 迁移、发件箱事件、多租户表。
- `tools-registry.md`:工具定义、SPI/MCP 连接器、AST SQL 沙箱、指标语义注册表。
- `server-gateway.md`:FastAPI 路由、人工接管服务、技能管理端点。
- `admin-web.md`:10 个 CRUD 模块、统一 CRUD 套件(`useAdminCrud`、`DataTable` 等)、HITL 抽屉。
- `client-web.md`:客户端 SSE 聊天、多模态卡片渲染、人工接管切换。
- `shared-ui.md`:原子设计、卡片家族规格、SVG 图标规范。
- `observability.md`:带租户上下文的结构化日志、telemetry 追踪、token 成本统计。
- `tenant-configs-types.md`:租户配置注册表与共享契约类型。

---

## 5. 架构深潜

深入设计参见 `docs/architecture/`:

- **架构与代码库地图**:`docs/architecture/architecture.md`
- **HITL 与认知回溯**:`docs/architecture/hitl-replanning.md`
- **Contextual RAG 与多租户**:`docs/architecture/contextual-rag.md`
- **多模态视觉与富卡片**:`docs/architecture/multimodal-and-rich-cards.md`


当上下文占用超过 60% 时，主动提醒我执行 `/compact` 压缩。
压缩时保留：代码变更记录、待办清单、核心问题定位、测试结果；丢弃探索过程和冗余解释。


## 模型档位使用规则
1. 简单任务（格式调整、代码注释、单文件小修改、运行命令、查日志）：
   主动提醒我切换到 Haiku 档，执行命令：/model claude-haiku-4-5
   对应 glm-5.3-flash，节省积分。

2. 常规任务（功能开发、普通调试、多文件修改）：
   保持默认 Sonnet 档即可，对应 glm-5.3。

3. 复杂任务（架构设计、深度重构、复杂bug排查）：
   主动提醒我切换到 Opus 档，执行命令：/model claude-opus-4-6
   用最强推理策略。

4. 切换档位尽量在任务开始前切换，中途不要频繁切换，避免破坏提示缓存。
