# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. Development Commands

### 1.1 Running Services

- **Start All Services:** `bun run dev:all` (frontends via turbo + Python services separately)
- **Start Web App:** `bun run dev:web` (Port 3000, Vite 6 SPA)
- **Start Admin Control Plane:** `bun run dev:admin` (Port 3001, Vite 6 SPA)
- **Start FastAPI Gateway:** `bun run dev:server` (Port 4000, `uv run uvicorn gateway_py.main:app --reload`)
- **Start Standalone Merchant App:** `bun run dev:merchant` (Port 3005, Next.js; `/api/*` and `/spi/*` proxied to gateway-py)
- **Start Temporal Worker:** `bun run worker` (`uv run python -m engine_py.temporal.worker`, task queue `agent-tasks-py`)

### 1.2 Build, Lint & Format

- **Build Frontend Workspaces:** `bun run build`
- **Lint Codebase:** `bun run lint`
- **Biome Lint & Check:** `bun run biome:check` / `bun run biome:format`
- **Python lint (ruff):** `cd services/engine-py && uv run ruff check .` (same for gateway-py)

### 1.3 Testing & Evaluation

- **Run Gateway Contract Tests:** `bun run test:eval` (pytest in `services/gateway-py`, sealed testcontainers PG+Redis)
- **Run a Single Test File:** `cd services/gateway-py && uv run pytest tests/test_http_routes_contract.py`
- **Run Playwright E2E Tests:** `bun run test:e2e`
- **Run Promptfoo Evaluations:** `bun run test:prompt` (Classify) / `bun run test:prompt:planner` (Planner)
- **Pin / Compare Promptfoo Baselines:** `bun run test:prompt:pin` / `bun run test:prompt:compare`

### 1.4 Database & Infrastructure

- **Start Core Docker Services:** `bun run docker:up` (PostgreSQL + Redis)
- **Start Temporal Cluster:** `bun run docker:temporal`
- **Stop Docker Services:** `bun run docker:down`
- **Apply Schema Migrations:** `bun run db:push` (Alembic `upgrade head` in `services/engine-py`)
- **Seed Database:** `bun run db:seed` (engine seed + third-party seed + merchant seed)

---

## 2. High-Level Architecture Map

Monorepo managed with Turborepo and Bun workspaces (frontend) plus a uv workspace (Python services):

```text
┌────────────────────────────────────────────────────────────────────────┐
│                    Frontend Applications (apps/, TypeScript)           │
│  - apps/web:      Vite 6 + React 19 Client Chat SPA (SSE, Cards)       │
│  - apps/admin:    Vite 6 + React 19 SaaS Control Plane (10 Modules)    │
│  - apps/merchant: Standalone Merchant Portal (Next.js; proxies to py)  │
└───────────────────────────┬────────────────────────────────────────────┘
                            │ HTTP / SSE / socket.io
                            ▼
┌────────────────────────────────────────────────────────────────────────┐
│              API Gateway (services/gateway-py, Python/FastAPI)         │
│  - 39 contract-frozen routes: tenants, skills, approvals, chat SSE,   │
│    conversations, RAG docs, personas, guardrails, billing, logs,      │
│    merchant store/admin, SPI v1 (HMAC-signed)                         │
│  - Realtime: SSE (Redis Streams event source) + python-socketio       │
│    live-takeover rooms (joined_room / peer_joined / typing / ...)     │
└───────────────────────────┬────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────────────────┐
│           Decision Engine (services/engine-py, Python/LangGraph)       │
│  LangGraph DAG: triage ──→ planner ──→ merge ──→ loop [exec ⇄ val]    │
│  - Skills Pipeline: BaseSkill, SOP rules, Tenant config overrides     │
│  - Memory: Quad-Memory (Short/Long/Episodic/Task) + Dual-Tier Persona │
│  - Contextual RAG: Context-enhanced chunks + tenant-filtered search   │
│  - HITL: ApprovalGatekeeper + Transactional Outbox Worker             │
│  - Orchestration: Temporal workflow (queue agent-tasks-py) with local │
│    simulation fallback; shadow-harness diff/replay against frozen TS  │
│  - Event backbone: Redis Streams (seq + XADD maxlen per job)          │
│  - DB ownership: SQLAlchemy models + Alembic migrations               │
└──────────────┬─────────────────────┬───────────────────────────────────┘
               │                     │
               ▼                     ▼
┌──────────────────────────┐ ┌──────────────────────────────────────────┐
│  packages/ui             │ │  packages/types                          │
│  - Zero-dep Atoms        │ │  - Frozen frontend contract types (zod)  │
│  - Rich Card Family      │ │  - Card / Skill / Tool DTOs shared by    │
│  - SVG Icon Library      │ │    web + admin + merchant (TS-only)      │
└──────────────────────────┘ └──────────────────────────────────────────┘
```

Backend history: the original TypeScript backend (`apps/server` NestJS gateway, `packages/{engine,tools,db,business-configs,observability}`) was retired after a 1:1 Python port (2026-09). `packages/types` is retained as the frozen frontend contract; behavior of retired TS code is pinned by the pytest contract suite in `services/gateway-py/tests/`.

---

## 3. Core Architectural Invariants

1. **Multi-Tenant Physical & Logical Isolation**:
   - Every database query and tool execution must include `tenantId` / `businessId`.
   - Dual-Tier Persona memory strictly separates `scope = 'global'` (general user traits) from `scope = 'tenant'` (brand-specific preferences).
2. **Skills & Tools Execution Pipeline**:
   - Follows `Planner ➔ Skill ➔ SPI/MCP Connector ➔ Service/DB`.
   - Business actions extend `BaseSkill` with declarative SOP validation, lifecycle hooks (`pre_execute`, `execute`, `post_execute`), and tenant config overrides.
   - Low-level external integrations use HMAC-SHA256 signatures, replay protection, and SSRF-guarded connectors.
3. **HITL Approvals & Transactional Outbox**:
   - Sensitive actions (refunds above threshold, address alterations) suspend execution into `pending_approvals`.
   - Outbox events (`approval_outbox_events`) are atomically committed with approval transitions, then resumed deterministically via the outbox worker.
4. **Parameterized AST SQL Sandbox**:
   - NL2SQL uses AST parser inspection to enforce `SELECT` only, injects tenant boundaries, appends `LIMIT 50`, and executes under read-only transaction timeouts.
5. **Zero-Dependency Shared UI**:
   - `apps/web` and `apps/admin` utilize `@agent-all/ui` with Tailwind CSS — do not add heavy external component frameworks.
6. **Contract Freeze**:
   - The 39 HTTP routes, SSE wire format, and socket.io events are frozen at the TS baseline; the pytest contract suite (`services/gateway-py/tests/`) is the source of truth.

---

## 4. Workspace Rules Reference

Detailed domain rules and coding guidelines are organized by module in `.claude/rules/`:

- `agent-engine.md`: LangGraph topology, Skills registry, Quad-Memory, Contextual RAG, Temporal workflows.
- `database-schema.md`: SQLAlchemy models, Alembic migrations, outbox events, multi-tenant tables.
- `tools-registry.md`: Tool definitions, SPI/MCP connectors, AST SQL sandbox, metric semantic registry.
- `server-gateway.md`: FastAPI routers, live takeover services, skills management endpoints.
- `admin-web.md`: 10 CRUD modules, unified CRUD suite (`useAdminCrud`, `DataTable`, etc.), HITL drawer.
- `client-web.md`: Client SSE chat, multi-modal card rendering, live takeover transitions.
- `shared-ui.md`: Atomic design, card family specs, SVG icon guidelines.
- `observability.md`: Structured logging with tenant contexts, telemetry traces, token cost tracking.
- `tenant-configs-types.md`: Tenant configuration registry and shared contract types.

---

## 5. Architectural Deep Dives

Refer to `docs/architecture/` for comprehensive designs:

- **Architecture & Codebase Map**: `docs/architecture/architecture.md`
- **HITL & Cognitive Backtracking**: `docs/architecture/hitl-replanning.md`
- **Contextual RAG & Multi-Tenant**: `docs/architecture/contextual-rag.md`
- **Multimodal Vision & Rich Cards**: `docs/architecture/multimodal-and-rich-cards.md`


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
