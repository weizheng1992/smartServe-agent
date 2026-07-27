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

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 4.1 Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 4.2 Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 4.3 Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4.4 Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
