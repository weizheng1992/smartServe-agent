---
description: Core LangGraph, parallel execution, and Temporal Agent Engine rules
paths: ["packages/engine/**/*"]
---

# Core Agent Engine Rules

This workspace houses the core Agent state machines, memory subsystems, parallel subtask executor, and Temporal workflows.

## Architecture

- **Dual Modes:** Uses a local high-fidelity LangGraph simulator as fallback when Temporal (port `7239`) is offline.
- **Workflow Orchestration:** `agentWorkflow` compiles as a durable Temporal workflow driving the state graph (`triage` → `planner` → `merge` → loop [`executor` ⇄ `validator`] → `finish`).
- **3-Tier Triage & Fast-Path:**
  - **First Shield:** Semantic duplicate query cache bypass (cosine similarity $\ge 0.98$).
  - **Multi-Intent Fast-Path:** Simple or independent single-intent queries bypass full planning loops into direct synthesis.
- **Parallel Subtask Executor:**
  - Independent subtasks with empty `dependencies` execute concurrently via `Promise.allSettled` in `stepExecutionEngine.ts`.
  - Dependent subtasks resolve sequentially following dependency topology order.
- **Memory Subsystems:** Quad-memory architecture (`ShortMemory`, `LongMemory`, `TaskMemory`, `EpisodicMemory`) with database-level self-healing fallback when in-memory `shortMemory` is empty.

## Guidelines

- Always preserve the **Semantic Duplicate Bypass** shield in `triageNode`.
- Keep subtask dependency declarations explicit in `planner.node.ts` to ensure safe parallel execution in `executor.node.ts`.
- Memory lookups must handle self-healing gracefully without throwing on empty cold starts.
- Keep LLM and embedding initialization unified via `callLLMWithRetry`.
- Temporal activities must isolate errors with standard try/catch and emit friendly Chinese localization logs to the UI.
