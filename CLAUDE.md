# CLAUDE.md

## 1. Development Commands

- **Start All Services:** `bun run dev`
- **Build All Workspaces:** `bun run build`
- **Start Production App:** `bun run start`
- **Lint Codebase:** `bun run lint`
- **Run Web App:** `bun --filter web dev`
- **Run Admin App:** `bun --filter admin dev`
- **Run Temporal Worker:** `bun --filter engine worker`
- **Generate DB Migrations:** `bun drizzle-kit generate`
- **Push Schema changes to DB:** `bun drizzle-kit push`

---

## 2. High-Level Architecture Map

Monorepo powered by Turborepo & Bun workspaces:

- `apps/web`: Vite 6 + React 19 SPA. Connects via `/api/chat` and `/api/chat/[jobId]/stream` (SSE).
- `apps/admin`: Vite 6 + React 19 SPA. HITL approval audit desk, multi-tab context drawer, and telemetry dashboard.
- `packages/engine`: LangGraph agent graph (`triage` → `planner` → `merge` → loop [`executor` ⇄ `validator`] → `finish`) and Temporal workflow orchestration (`agentWorkflow`). Falls back to local simulator when Temporal is offline.
- `packages/db`: Drizzle ORM PostgreSQL client connecting directly to physical PostgreSQL instance.
- `packages/tools`: External tools (`getOrderStatus`, `processRefund`, Puppeteer `takeScreenshot`, `listUserOrders`, `createOrder`, OpenAPI dynamic tools).
- `packages/observability`: Pino logger and Langfuse tracing.
- `packages/business-configs`: Multi-tenant business schema configurations.
- `packages/types`: Monorepo shared type definitions (cards, agent, approval, config, tool, etc.).
- `packages/ui`: Zero-external-dependency shared UI components, SVG icons, and rich interactive card family.

_Workspace rules are in `.claude/rules/*.md`._

---

## 3. Core Architectural Guides

Deep designs located in `docs/architecture/`:

- **Architecture & Codebase Map**: `docs/architecture/architecture.md`
- **HITL & Cognitive Backtracking**: `docs/architecture/hitl-replanning.md`
- **Contextual RAG & Multi-Tenant**: `docs/architecture/contextual-rag.md`
- **Multimodal Vision & Rich Cards**: `docs/architecture/multimodal-and-rich-cards.md`

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
