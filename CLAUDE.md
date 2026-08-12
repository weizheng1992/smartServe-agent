# CLAUDE.md

## 1. Development Commands

- **Start All Services:** `bun run dev`
- **Build All Workspaces:** `bun run build`
- **Start Production App:** `bun run start`
- **Lint Codebase:** `bun run lint`
- **Run Next.js Web App:** `bun --filter web dev`
- **Run Temporal Worker:** `bun --filter engine worker`
- **Generate DB Migrations:** `bun drizzle-kit generate`
- **Push Schema changes to DB:** `bun drizzle-kit push`

---

## 2. High-Level Architecture Map

Monorepo powered by Turborepo & Bun workspaces:

- `apps/web`: Next.js 15 App Router. Connects via `/api/chat` and `/api/chat/[jobId]/stream` (SSE).
- `packages/engine`: LangGraph agent graph (`triage` → `planner` → `merge` → loop [`executor` ⇄ `validator`] → `finish`) and Temporal workflow orchestration (`agentWorkflow`). Falls back to local simulator when Temporal is offline.
- `packages/db`: Drizzle ORM PostgreSQL client with in-memory `FakePool` fallback when offline.
- `packages/tools`: External tools (`getOrderStatus`, `processRefund`, Puppeteer `takeScreenshot`, `listUserOrders`).
- `packages/observability`: Pino logger and Langfuse tracing.
- `packages/business-configs`: Multi-tenant business schema configurations.

_Workspace rules are in `.claude/rules/*.md`._

---

## 3. Core Architectural Guides

Deep designs located in `.claude/docs/`:

- **Architecture & Codebase Map**: `.claude/docs/architecture.md`
- **HITL & Cognitive Backtracking**: `.claude/docs/hitl-replanning.md`
- **Contextual RAG & Multi-Tenant**: `.claude/docs/contextual-rag.md`

---

## 4. General Behavioral Rules

### 4.1 Think Before Coding

- State assumptions explicitly. Surface tradeoffs and push back if a simpler approach exists.

### 4.2 Simplicity First

- Write minimum code solving the prompt. Avoid speculative features or single-use abstractions.

### 4.3 Surgical Changes

- Touch only necessary code. Clean up unused imports/variables created by your changes, but leave pre-existing dead code untouched.

### 4.4 Goal-Driven Execution

- Define verifiable goals and run tests/linters before declaring completion.
