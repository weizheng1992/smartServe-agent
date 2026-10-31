# TechDesign —— agent-platform 技术基线(溯源)

> **文档性质声明**:同 PRD,本文为 2026-10-31 补写的溯源基线,从 `CLAUDE.md` §2、`docs/architecture/`、`docs/adr/` 压缩而成;架构决策的完整推理以各 ADR 原文为准。

## 1. 拓扑

四个前端 SPA(Vite 6 + React 19)→ FastAPI 网关(gateway-py,137 端点,SSE + socket.io)→ LangGraph 决策引擎(engine-py)→ PG18 双库(agent_platform / agent_merchant)+ Redis(Streams 事件主干、审批对账、房间广播)。

## 2. 关键架构决策(ADR 索引)

- **ADR-0007**:回合管线收敛为 `run_agent` 单一深模块;Temporal 路线 2026-09-30 退役,重引入须新立 ADR。
- **ADR-0010**:Data Agent 分层信任——LLM 只产意图与参数,SQL 由闭集模板编译,经 AST 守卫(`sql_guard.py`),租户谓词服务端注入不可剥离。
- **ADR-0011**:归因增强边界(提议待裁决)。
- **ADR-0013**:聊天断线收口(重连补投语义)。
- **ADR-0015**:本体知识层——`ontology/` 为领域知识单一事实源,闭集词汇 + 生成物消费,漂移门 = pytest 一致性册 + CI regen diff。

## 3. 信任边界与安全

- 敏感动作:BaseSkill 声明 `requiresApproval` 与阈值,挂起写 `pending_approvals`,审批变更与 outbox 事件同事务;恢复经确定性 JobId Fast-Path,outbox worker 兜底对账(`FOR UPDATE SKIP LOCKED`)。
- 外部集成:SPI v1 HMAC-SHA256 签名 + 防重放 + SSRF 防护连接器。
- 多租户:一切查询携带 tenantId/businessId;商户真单库只读跨接(`_merchant_reader_engine`);分析 SQL 在只读事务超时下执行。

## 4. 数据所有权

engine-py 独占 SQLAlchemy 模型与 Alembic 迁移;引擎侧与商户侧双库分离;记忆双层画像按 scope 隔离;RAG 切片租户过滤。

## 5. 部署形态

单实例假设(gateway lifespan 承载 scheduler;多实例前置清单见 `docs/architecture/multi-instance-deployment.md`)。生产 Docker Compose:场景 A 四前端 nginx 一体,场景 B 仅商户面;镜像 GHCR;两机拓扑 PG 在 A 机。dev 侧四前端 + uvicorn reload(engine-py 改动需 touch gateway 文件触发热重载)。

## 6. 元数据

```json
{
  "schemaVersion": 1,
  "documentType": "techdesign",
  "appName": "agent-platform",
  "stack": {
    "frontend": "Vite 6 + React 19 SPA ×4(Turborepo + Bun workspaces)",
    "backend": "FastAPI gateway-py + LangGraph engine-py(uv workspace)",
    "database": "PostgreSQL 18 双库 agent_platform / agent_merchant + SQLAlchemy + Alembic;Redis Streams",
    "auth": "自建:消费者显式身份(guest-* / CUST-*),员工 JWT(merchant-admin 收口),SPI HMAC-SHA256",
    "styling": "Tailwind CSS v4 + workspace 包 ui(shadcn 无头原子,零组件库依赖)",
    "deployment": "Docker Compose + nginx(GHCR 镜像,两机拓扑,--env-file 必带)"
  },
  "commands": {
    "setup": "bun run docker:up && bun run db:init-external && bun run db:push && bun run db:seed",
    "dev": "bun run dev:all",
    "test": "bun run test:eval",
    "typecheck": "bun run build",
    "lint": "bun run lint",
    "build": "bun run build"
  },
  "aiScope": "agent"
}
```

