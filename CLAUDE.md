# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. Development Commands

### 1.1 Running Services

- **Start All Services:** `bun run dev:all` (or `bun run dev` for web + merchant)
- **Start Web App:** `bun run dev:web` (Port 3000, Vite 6 SPA)
- **Start Admin Control Plane:** `bun run dev:admin` (Port 3001, Vite 6 SPA)
- **Start NestJS API Gateway:** `bun run dev:server`
- **Start Standalone Merchant App:** `bun run dev:merchant`
- **Start Temporal Worker:** `bun run worker`

### 1.2 Build, Lint & Format

- **Build All Workspaces:** `bun run build`
- **Lint Codebase:** `bun run lint`
- **Biome Lint & Check:** `bun run biome:check` / `bun run biome:format`

### 1.3 Testing & Evaluation

- **Run All Unit / Integration Tests:** `bun test`
- **Run a Single Test File:** `bun test <path/to/file.test.ts>` (e.g. `bun test packages/engine/tests/skillsRegistry.test.ts`)
- **Run Playwright E2E Tests:** `bun run test:e2e`
- **Run Promptfoo Evaluations:** `bun run test:prompt` (Classify) / `bun run test:prompt:planner` (Planner)
- **Run Full E2E Eval:** `bun run test:eval`
- **Run Load Tests:** `bun run test:load`

### 1.4 Database & Infrastructure

- **Start Core Docker Services:** `bun run docker:up` (PostgreSQL + Redis)
- **Start Temporal Cluster:** `bun run docker:temporal`
- **Stop Docker Services:** `bun run docker:down`
- **Push Schema changes to DB:** `bun run db:push`
- **Seed Database:** `bun run db:seed`
- **Run Idempotent Column Migrations:** `bun packages/db/src/migrateColumns.ts`

---

## 2. High-Level Architecture Map

Monorepo managed with Turborepo and Bun workspaces:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                          Applications (apps/)                          │
│  - apps/web:      Vite 6 + React 19 Client Chat SPA (SSE, Cards)       │
│  - apps/admin:    Vite 6 + React 19 SaaS Control Plane (10 Modules)    │
│  - apps/server:   NestJS API Gateway & Realtime Takeover Gateway       │
│  - apps/merchant: Standalone Merchant Portal & SPI Endpoints           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     Decision Engine (packages/engine)                  │
│  LangGraph DAG: triage ──→ planner ──→ merge ──→ loop [exec ⇄ val] ──→ finish
│  - Skills Pipeline: BaseSkill, SOP rules, Tenant config overrides      │
│  - Memory: Quad-Memory (Short/Long/Episodic/Task) + Dual-Tier Persona  │
│  - Contextual RAG: Context-enhanced chunks + tenant-filtered search    │
│  - HITL: ApprovalGatekeeper + Transactional Outbox Worker              │
│  - Orchestration: Temporal workflow with local simulation fallback     │
└──────────────┬────────────────────┬────────────────────┬───────────────┘
               │                    │                    │
               ▼                    ▼                    ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│  packages/db         │ │  packages/tools      │ │  packages/ui         │
│  - Drizzle ORM PG    │ │  - Tool Registry     │ │  - Zero-dep Atoms    │
│  - Outbox Events     │ │  - SPI/MCP Connectors│ │  - Rich Card Family  │
│  - Tenant Isolation  │ │  - AST NL2SQL Sandbox│ │  - SVG Icon Library  │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
               │                    │                    │
               ▼                    ▼                    ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│  packages/types      │ │  packages/business-  │ │  packages/observa-   │
│  - Single source DTOs│ │  configs             │ │  bility              │
│  - Skill, Tool types │ │  - Tenant registry   │ │  - Pino + Langfuse   │
│  - Card schemas      │ │  - Config merging    │ │  - Cost & Telemetry  │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
```

---

## 3. Core Architectural Invariants

1. **Multi-Tenant Physical & Logical Isolation**:
   - Every database query and tool execution must include `tenantId` / `businessId`.
   - Dual-Tier Persona memory strictly separates `scope = 'global'` (general user traits) from `scope = 'tenant'` (brand-specific preferences).
2. **Skills & Tools Execution Pipeline**:
   - Follows `Planner ➔ Skill ➔ SPI/MCP Connector ➔ Service/DB`.
   - Business actions extend `BaseSkill` with declarative SOP validation, lifecycle hooks (`preExecute`, `execute`, `postExecute`), and tenant config overrides.
   - Low-level external integrations use HMAC-SHA256 signatures, replay protection, and SSRF-guarded connectors.
3. **HITL Approvals & Transactional Outbox**:
   - Sensitive actions (refunds above threshold, address alterations) suspend execution into `pending_approvals`.
   - Outbox events (`approval_outbox_events`) are atomically committed with approval transitions, then resumed deterministically via `approvalOutboxWorker`.
4. **Parameterized AST SQL Sandbox**:
   - NL2SQL uses AST parser inspection to enforce `SELECT` only, injects tenant boundaries, appends `LIMIT 50`, and executes under read-only transaction timeouts.
5. **Zero-Dependency Shared UI**:
   - `apps/web` and `apps/admin` utilize `@agent-all/ui` with Tailwind CSS — do not add heavy external component frameworks.

---

## 4. Workspace Rules Reference

Detailed domain rules and coding guidelines are organized by module in `.claude/rules/`:

- `agent-engine.md`: LangGraph topology, Skills registry, Quad-Memory, Contextual RAG, Temporal workflows.
- `database-schema.md`: Drizzle ORM schemas, outbox events, multi-tenant tables, migrations.
- `tools-registry.md`: Tool definitions, OpenAPI factories, SPI/MCP connectors, AST SQL sandbox.
- `server-gateway.md`: NestJS controllers, live takeover services, skills management endpoints.
- `admin-web.md`: 10 CRUD modules, unified CRUD suite (`useAdminCrud`, `DataTable`, etc.), HITL drawer.
- `client-web.md`: Client SSE chat, multi-modal card rendering, live takeover transitions.
- `shared-ui.md`: Atomic design, card family specs, SVG icon guidelines.
- `observability.md`: Pino logging with tenant contexts, Langfuse traces, token cost tracking.
- `tenant-configs-types.md`: Tenant configuration registry and centralized TypeScript types.

---

## 5. Architectural Deep Dives

Refer to `docs/architecture/` for comprehensive designs:

- **Architecture & Codebase Map**: `docs/architecture/architecture.md`
- **HITL & Cognitive Backtracking**: `docs/architecture/hitl-replanning.md`
- **Contextual RAG & Multi-Tenant**: `docs/architecture/contextual-rag.md`
- **Multimodal Vision & Rich Cards**: `docs/architecture/multimodal-and-rich-cards.md`
