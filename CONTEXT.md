# Domain Context & Architectural Glossary

This document serves as the single source of truth for domain vocabulary and module shapes across the codebase.

## Chat Cards & Quick Replies Subsystem (engine-py)

### CardSynthesizer (`services/engine-py/src/engine_py/cards/card_synthesizer.py`)

The card assembly layer that turns finished graph state into rich card payloads (ADR-0001):

- **Scene-Conditional Quick Replies (`场景组`)**: Every reply carries ONE `quick_replies` capsule chosen by the turn's classified intents — refund scene (`refund`/`order_return`), category chips from the live merchant shelf (`shopping_guide`), or the default generic set. Every button must be backed by a real capability (**死按钮禁令** — the data-honesty iron rule extended to UI interactions); hot-selling wording follows the **data-conditional ban** (ADR-0002): a dedicated 🔥 entry backed by real sales aggregation is allowed, while category chips themselves never claim heat (the merchant shelf still has no sales column — rankings aggregate real merchant orders, refunds excluded).
- **Base Precedence & First-Wins**: Domain cards emitted by skills win as the base; skill-authored quick_replies (e.g. damage-photo disambiguation) are kept verbatim and suppress the scene capsule (never two capsules per screen); product_ranking cards always get the metric-disambiguation set.
- **`fetch_shelf_categories`**: Guide-turn-only live shelf overview; zero DB queries on other turns; honest-empty (falls back to the generic set) on failure — never a static fake catalog.

### Shipping-Status Order Filter (`services/engine-py/src/engine_py/tools_registry/order_domain.py`)

`list_user_orders(shipping_status)` — `UNSHIPPED` = still awaiting shipment (excludes shipped/delivered/refunded/cancelled), `SHIPPED`, `DELIVERED`; case-insensitive; invalid values error honestly instead of silently returning everything. Both order sources (merchant real orders / engine local table) share one pure filter (`_apply_shipping_filter`) so the two paths can never drift.

## Execution & Gatekeeping Subsystem

### ApprovalGatekeeper (`services/engine-py/src/engine_py/approvals/gatekeeper.py`)

A deep domain gatekeeper subsystem unifying security policy evaluation, pending approval lifecycle management, and execution resumption (Redis SETNX 分布式锁 + 内存后备锁、决议状态机、事务发件箱与断点续跑):

- **Security & Policy Rules**: `check_double_refund` against physical database status, `evaluate_refund_auto_approval` threshold evaluation against tenant business configs, and `evaluate_address_change_policy` high-value shipping address change interception.
- **Ticket Lifecycle & Concurrency**: Manages pending ticket creation (`waiting`), deadline auto-expiration (`expired`), Redis SETNX locks with in-memory fallback sets, and 决议状态机迁移 (`approved`, `rejected`, `cancelled`, `resolved_by_human`) — status change and `approval_outbox_events` commit **in the same DB transaction** (transactional outbox).
- **Resumption & IM Takeover**: Resumes suspended executions via the synchronous Fast-Path with the deterministic job id `job_resume_{approvalId}` (physically idempotent); events left `pending` by a failed dispatch are reconciled by `approvals/outbox_worker.py` (`FOR UPDATE SKIP LOCKED`, scheduled by `engine_py/scheduler.py`).

### Memory Quartet (`services/engine-py/src/engine_py/memory/`)

The TS `AgentMemoryEngine` facade was not ported as a single class; `run_agent.py` orchestrates the four tiers directly:

- `ShortMemory` (`short_memory.py`): sliding recent-history reads from the `messages` table (with self-heal when empty); assistant rows are engine-authored, user rows are gateway-authored (single-write ownership).
- `LongMemory` (`long_memory.py`): persona facts with cosine retrieval (hard threshold ≥ 0.65).
- `TaskMemory` (`task_memory.py`): suspended task plans persisted the moment an approval ticket becomes visible (`skills/suspension.py` is the only implementation seam).
- `EpisodicMemory` (`episodic_memory.py`): importance-scored business events with dual-tier tenant visibility (`scope=global` vs `scope=tenant` + `business_id`).
- **Parallel Gathering (run_agent)**: history, long-term facts, and episodic events are fetched concurrently per turn and fed into prompt assembly; turn recording writes back assistant messages, extracted facts, plans, and events non-blockingly.

### NL2SQL Sandbox — retired, zero callers

The TS `NLMetricQueryEngine` was retired with the TS backend and **not ported** (the TS baseline already had zero call sites). The Data Agent never generates SQL text (iron rule 08-D1): intents resolve to a closed set of `StructuredQueryIntent` shapes and SQL is assembled deterministically from per-metric templates, audited read-only by `analytics/sql_guard.py` (AST SELECT-only + LIMIT). Do not route NL-to-SQL features through any generative path without a new ADR.

### StepExecutionEngine (`services/engine-py/src/engine_py/graph/nodes/step_execution_engine.py`)

A deep module facade that orchestrates the execution of individual task plan subtasks:

- Fast-path tool matching (`try_match_executor_fast_path`) with a serial guard for skill-chain steps; independent steps dispatched concurrently
- HITL suspension via `skills/suspension.py` (`suspend_for_approval`) — the only ticket-creation seam
- Tool execution dispatching against a whitelisted base-tools set, plus result logging
- User-friendly localized (中文) progress event emission

Financial safety policy checks (double-refund, thresholds) live in `approvals/gatekeeper.py` — the TS `ApprovalPolicyEngine` class was merged there. The TS `ExecutionOutcome` value object was not ported; execution steps return plain dicts (`{task_plan updates, status, result|error, counter increments}`).

## Database & Persistence Subsystem

### FakePool — retired with the TS backend

The in-memory SQL emulator was TS-only. The Python stack always talks to real PostgreSQL (SQLAlchemy async + Alembic migrations; contract tests spin sealed testcontainers PG+Redis via `services/gateway-py/tests/conftest.py`).

### Gateway Repositories (`services/gateway-py/src/gateway_py/`)

Domain repository modules that decouple HTTP routes from raw SQL:

- `conversation_repo.py`: thread lifecycle (idempotent upsert, ownership guards, self-heal claiming), message persistence, takeover status machine (`update_conversation_status` with the `__unset__` sentinel for `assigned_operator_id`), timeline reads.
- `merchant_db.py` / `merchant_domain.py`: merchant real orders/promotions/vouchers in the separate `agent_merchant` database (raw SQL, read-only reader from the engine side).
- Engine-side ownership: SQLAlchemy models + Alembic migrations in `services/engine-py/src/engine_py/db.py` / `alembic/`.

## RAG Knowledge Subsystem

### Contextual RAG (`services/engine-py/src/engine_py/rag/contextual_rag.py`)

The RAG facade across multi-tenant knowledge bases (see `docs/architecture/contextual-rag.md`):

- **Contextual Chunking**: slices gain LLM-written contextual summaries prefixed at ingestion; embeddings stored per chunk.
- **Tenant Physical Isolation**: retrieval filters `WHERE business_id = :tenant_id` — cross-tenant policy confusion is physically blocked.
- **Supporting Modules**: `knowledge_files.py` (file-level ingestion/replacement lifecycle) and `product_knowledge.py` (product-facing retrieval).

## API & Service Layer Subsystem

### Chat Router (`services/gateway-py/src/gateway_py/routers/chat.py`)

The chat session orchestration surface (absorbs the TS `ChatSessionOrchestrator`):

- **Job Acceptance & Dispatch**: enqueues agent jobs and drives `engine_py.run_agent.run_agent` (asyncio task with a second-level degradation net around the graph's own fallback).
- **Human Support Session Bypass**: active human takeover (`human_takeover` status) routes messages to persistence without triggering agent graph execution.
- **SSE Streaming (`/api/chat/{jobId}/stream`)**: event source is Redis Streams itself — `Last-Event-ID` replay re-reads the stream; heartbeats keep clients alive.
- **Thread Management**: explicit thread create (idempotent, with onboarding greeting rows), strict-equality user listing, cascade delete preserving audit records.

### Approval Surface (`services/gateway-py/src/gateway_py/routers/admin.py` + `engine_py.approvals.gatekeeper.process_approval_action`)

HITL ticket lifecycle management (absorbs the TS `ApprovalService`):

- **Pending Ticket Querying**: pending approvals joined with tenant metadata for the admin queue.
- **Concurrency & Lock Control**: Redis SETNX (`lock:approval:{id}`, PX 5000) with in-memory fallback sets to prevent double-submit collisions.
- **Agent Resumption Dispatching**: atomically transitions ticket statuses (`approved`, `cancelled`, `rejected`, `resolved_by_human`), writes the outbox event in the same transaction, and dispatches resumption via the deterministic `job_resume_{approvalId}` Fast-Path.

### AgentStreamClient (`apps/web/src/lib/agentStreamClient.ts`)

A dedicated SSE network stream client that decouples EventSource transport, event parsing, and localized node name mapping from React UI hooks:

- **EventSource Transport Management**: Handles SSE connection establishment, event listener binding, and safe resource cleanup.
- **Typed Event Dispatching**: Emits structured status, result, and error events to UI subscribers (`onStatus`, `onResult`, `onError`).

### Temporal Workflow Layer (`services/engine-py/src/engine_py/temporal/`)

Durable execution route (absorbs the TS `WorkflowOrchestrator`):

- `workflows.py`: `agentWorkflow` replays the LangGraph node loop as Temporal activities (queue `agent-tasks-py`), with status/plan/result Query handlers.
- `activities.py`: `run_agent_state_node` bridges single graph nodes into activity executions.
- `worker.py`: worker entrypoint (started via `bun run worker`).
- **Local Fallback**: when Temporal is unreachable, jobs run directly as local asyncio graph executions — the gateway never hard-depends on the Temporal cluster (see `docs/deployment.md`).

## Skills Subsystem (engine-py)

### Typed Skill Contract (`services/engine-py/src/engine_py/skills/contract.py`)
`SkillContext` / `SkillResult` are the sole interface between skills and their two production callers — the triage skill fast-track and the step executor dispatch are the two adapters that translate to/from the online camelCase dict once each (`to_dict()` shape frozen by `tests/test_skill_contract_golden.py`). Domain contexts (`guide_context` / `cart_context` / `order_context`) are fields, not key conventions: a concept like the per-turn cart additions (`cart_context.addedThisTurn`, consumed by the composite add-then-checkout scoped checkout) lives in one place instead of threading through five layers. `executor_node` returns `cart_context` upward (same dead-write fix as guideContext, 2026-09-12).

### Cart Action Table (`services/engine-py/src/engine_py/skills/cart/`)
CartManageSkill is a thin shell over `ACTION_TABLE` — verbs (checkout / order-bridge / view / delete / qty / vague-ask / add-all / add) are declarative rows (detector + handler); branch precedence is table order, not if-ladder. `resolver.py` is the single source for cart utterance regexes and `resolve_cart_item` (ordinal → name-match → lastModified → first) shared by delete/qty; `cards.py` owns cart_card assembly. The 920-line branch swamp this replaced produced the S6 wrong-order, phantom-Nike and dual-SKU dedup incidents.

### HITL Suspension Seam (`services/engine-py/src/engine_py/skills/suspension.py`)
`persist_suspended_plan` / `suspend_for_approval` are the only implementations of ticket creation + immediate plan persistence + response assembly (wayfinder 004: the recovery plan must hit TaskMemory the moment the approval ticket becomes visible to the 2s poller — the address-skill copy of this invariant used to sit after an unconditional `return` and never ran).
