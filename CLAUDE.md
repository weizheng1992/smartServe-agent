# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 1. Development Commands

### Common Tasks
- **Start All Services (Next.js + Standalone Dev):** `bun run dev`
- **Build All Workspaces:** `bun run build`
- **Start Production App:** `bun run start`
- **Lint Codebase:** `bun run lint`

### Standalone Runs
- **Run Next.js Web App:** `bun --filter web dev`
- **Run Temporal Worker:** `bun --filter engine worker` (or `cd packages/engine && bun run worker`)

### Database Commands (Drizzle)
- **Generate DB Migrations:** `bun drizzle-kit generate`
- **Push Schema changes to DB:** `bun drizzle-kit push`

---

## 2. High-Level Architecture Map

This monorepo is managed by Turborepo and powered by Bun workspaces:
- `apps/web`: Next.js 15 App Router. Connects via `/api/chat` (initiates) and `/api/chat/[jobId]/stream` (SSE stream).
- `packages/engine`: Core agent graph (LangGraph) and Temporal workflow orchestration (`agentWorkflow`). Falls back to a local high-fidelity simulator when Temporal is offline.
- `packages/db`: Drizzle ORM PostgreSQL connection. Implements a high-fidelity memory emulator fallback (`FakePool`) when offline.
- `packages/tools`: External tools (order status, refund, Puppeteer screenshots, order listing).
- `packages/observability`: Child logging (`pino`) and trace exports (`langfuse`).
- `packages/business-configs`: Multi-business schema configurations.

*Detailed workspace rules and code conventions are located in `.claude/rules/*.md` and are loaded dynamically based on path matches.*

---

## 3. Core Architectural Decisions & System Guides

All core architectural decisions, detailed designs, and technical guides are saved in `.claude/docs/`:
- **Architecture & Codebase Map**: `.claude/docs/architecture.md` (Contains deep file mappings, memory systems, resilient wrappers, and double-preventions)
- **HITL & Cognitive Backtracking**: `.claude/docs/hitl-replanning.md` (Contains dialogue/task separation, waiting suspension, cognitive re-planning, and user cancellations)
- **Contextual RAG & Multi-Tenant**: `.claude/docs/contextual-rag.md` (Contains multi-tenant isolation, Contextual Retrieval summaries, and SOP Guardrails)

*When modifying the graph nodes, memory structures, RAG, database clients, or tools, you MUST read and follow these design specifications to preserve system integrity and security boundaries!*

---

## 4. General Behavioral Rules

These guidelines bias toward caution over speed. For trivial tasks, use judgment.

1. **Think Before Coding:** Explicitly state assumptions. Stop and clarify if requirements or edge cases are confusing.
2. **Simplicity First:** Write the minimum code required to solve the task. No speculative abstractions or unnecessary configs.
3. **Surgical Changes:** Edit ONLY what you must. Match surrounding code styles and comment density. Never format or refactor unrelated files.
4. **Goal-Driven Execution:** Define success metrics. Verify implementations by running/mocking the local simulator and checking outputs and database mutations before declaring done.
