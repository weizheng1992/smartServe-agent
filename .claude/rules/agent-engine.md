---
description: Core LangGraph and Temporal Agent Engine rules
paths: ["packages/engine/**/*"]
---
# Core Agent Engine Rules

This workspace houses the core Agent state machines, memory subsystems, and Temporal workflows.

## Architecture
- **Dual Modes:** Uses a local high-fidelity LangGraph simulator as a fallback if the Temporal connection (port `7239`) is unavailable.
- **Workflow Orchestration:** `agentWorkflow` compiles as a durable Temporal workflow driving the agent state nodes (`triage` → `planner` → `merge` → loop [`executor` ⇄ `validator`] → `finish`).
- **3-Tier Triage:** Triage node uses rules bypasses, cached semantic embedding scores, and Gemini 3.5 Flash classification. Includes a **First Shield (Semantic Duplicate Bypass)** that intercepts exact or highly similar repeat queries (>= 0.98 cosine similarity) to bypass downstream LLM loops entirely.
- **Memory Subsystems:** Configured across 4 modular classes (`ShortMemory`, `LongMemory`, `TaskMemory`, `EpisodicMemory`).

## Guidelines
- Do not bypass state nodes or bypass the memory abstractions unless implementing direct greetings optimization (which must return formatted bypass payloads).
- Always respect the **Semantic Duplicate Bypass** shield in `triageNode`. If modifying triage pre-filters, do not disable or break the duplicate message lookup.
- Keep LLM and embedding initialization clean via the unified `callLLMWithRetry` helper.
- Temporal activity code should run standard error isolation (try/catch blocks) and forward friendly Chinese localization logs to the UI.
