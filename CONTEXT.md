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
- `LongMemory` (`long_memory.py`): persona facts with cosine retrieval (hard threshold ≥ 0.55).
- `TaskMemory` (`task_memory.py`): suspended task plans persisted the moment an approval ticket becomes visible (`skills/suspension.py` is the only implementation seam).
- `EpisodicMemory` (`episodic_memory.py`): importance-scored business events with dual-tier tenant visibility (`scope=global` vs `scope=tenant` + `business_id`).
- **Parallel Gathering (run_agent)**: history, long-term facts, and episodic events are fetched concurrently per turn and injected into the finish-node final-answer assembly (`[USER PROFILE MEMORY]` / `[MEMORY OF PAST EVENTS]` blocks with an anti-echo gate; the consult fast-path deliberately bypasses injection); turn recording writes back assistant messages, extracted facts, plans, and events non-blockingly.
- **Naming note ("persona" is overloaded)**: here it means the **memory persona** (`long_memory_facts`). Two unrelated homonyms: the Data Agent `customer_profile` merchant wide table (`analytics/engine.py`) and the product review-reputation profile (evaluation queries in `tools_registry/mall_domain.py`). See `agent-engine.md` §1.4 for the full disambiguation.

### NL2SQL Sandbox — retired, zero callers

The TS `NLMetricQueryEngine` was retired with the TS backend and **not ported** (the TS baseline already had zero call sites). The Data Agent never generates SQL text (iron rule 08-D1): intents resolve to a closed set of `StructuredQueryIntent` shapes and SQL is assembled deterministically from per-metric templates, audited read-only by `analytics/sql_guard.py` (AST SELECT-only + LIMIT). Do not route NL-to-SQL features through any generative path without a new ADR.

**Entity gate vs unsupported are distinct concepts (2026-10-03)**: compile-time entity gates ("勾选两单再对比" — one sentence away from answerable) raise `EntityGateRequired(UnsupportedQuery)` carrying `.hint`; the presentation layer dispatches by `isinstance`, never by sniffing exception/caliber text. Machine semantics travel in fields (`QueryResult.from_cache`), display strings are for humans only.

### StepExecutionEngine (`services/engine-py/src/engine_py/graph/nodes/step_execution_engine.py`)

A deep module facade that orchestrates the execution of individual task plan subtasks:

- Fast-path tool matching (`try_match_executor_fast_path`) with a serial guard for skill-chain steps; independent steps dispatched concurrently
- HITL suspension via `skills/suspension.py` (`suspend_for_approval`) — the only ticket-creation seam
- Tool execution dispatching against a whitelisted base-tools set, plus result logging
- User-friendly localized (中文) progress event emission

Financial safety policy checks (double-refund, thresholds) live in `approvals/gatekeeper.py` — the TS `ApprovalPolicyEngine` class was merged there. The TS `ExecutionOutcome` value object was not ported; execution steps return plain dicts (`{task_plan updates, status, result|error, counter increments}`).

### Skill Router (`services/engine-py/src/engine_py/skills/routing.py`)

The single home for skill-routing knowledge (2026-10-07, consolidated from five scattered sites — triage fast-track, `is_action_query` cache gate, `fallback_dispatcher` regexes, the step-engine outfit guard, and the tool-whitelist):

- **`match_skill(skills, context)`**: decided-intent exact `triggerIntents` match first (a keyword-fallback skill must never hijack a decided intent — 实弹:「推荐优惠最大的商品」), then `can_handle` keyword fallback for undecided input.
- **`is_action_shaped(skills, text)`**: boolean sniff for the semantic-cache write/read gates; fails closed (treat as action) — cache poisoning defence.
- **`is_money_action_vetoed(input, category)`**: fast-track yield predicate — refund-verb family ∧ non-after-sale skill must yield to structured triage (实弹矩阵 A6).
- **`reroute_tool(tool_name, input)`**: outfit-shape guard — `searchProducts` on 搭配-shaped input re-routes to `ShoppingGuideSkill` (实弹:工具路径丢双族补全); the outfit/anchor regexes are public class attributes of the skill (single source shared with the skill's own completion logic).
- **`route_fallback(question)`**: degraded-mode routing — promo wording / explicit order id / order-query intent (order status rendering itself lives in `order_domain.order_status_line`).

Layering discipline: matching functions accept the skills **sequence** (accept dependencies, don't create them); the vocabulary families stay in `triage/intent_registry` (single source) and are imported lazily inside functions — a top-level import would re-enter the `skills` package mid-initialisation through `triage/__init__`. The public interfaces are unchanged: `SkillRegistry.find_matching_skill` (classmethod, the tests' patch seam) and the `is_action_query` re-export in `intent_triage_engine` (the `ctx.ns` dynamic patch face) both delegate here.

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

### Gateway 深 module 三缝(架构审查落地,2026-10-04)

`services/gateway-py/src/gateway_py/` 的三个共享缝,路由声明、不再各自装配:

- **`tenant_scope.py`(租户边界与员工身份闸)**:身份解析(`resolve_staff` / `require_staff` / `optional_staff`,JWT→在职员工,租户由 DB 行带出)、租户边界(`bound_tenant`,他租/`all` 聚合 403)、商户注册表闸(`ensure_tenant_registered`,raise 型 fail-closed)、`same_tenant` 谓词与 `staff_scope` Depends。**两形规则**(契约钉死):身份/租户闸走 HTTPException `{"detail"}` 形,业务闸走 `GateError` → 全局 handler 渲染 `{"success": false, error|message}`。
- **`approval_actions.py`(审批动作装配)**:HITL 动作三通道(商户运营台 / 管理台顾客+坐席 / SPI)共享的机制单点 —— 动作词表(`CUSTOMER_ACTIONS`/`OPERATOR_ACTIONS`/`STAFF_REVIEW_ACTIONS`/`SPI_ACTIONS`)、对象级租户闸(ensure_*=success 形 / assert_*=detail 形)、humanReply 别名、operator 快照、引擎载荷装配。SPI 通道归属闸 2026-10-04 收口(全局 key 不得跨租户核销工单)。
- **`sse_tail.py`(SSE 读流泵)**:chat / analytics ask / merchant store 三份手抄泵的归一单点 —— `tail_stream`(历史回放 + XREAD 尾随 + 心跳 + 终局收口,`__done__` 类哨兵不出 SSE 线)、`tail_pubsub`(顾客侧频道 adapter)、`streaming_headers`。测试桩点唯一:monkeypatch 本 module 的 `get_client` / `read_agent_events`。

配套单点:engine 侧 `engine_py/db/merchant_access.py`(agent_merchant 库 URL 解析与 reader/writer/gateway 三执行位构造)、`order_domain.generate_order_id`(订单号六次闸,两包同一机制)与 `insert_merchant_order(_item)`(真账 INSERT 列清单唯一);gateway 侧 `approval_actions` 动作词表与 `conversation_repo.thread_owner`(线程属主访问器)。`conversation_repo.update_conversation_status` 内嵌接管不变量:任何把 human_takeover 线程改走的状态写自动清除暂停闸元数据键(坐席字段保留为审计痕迹,契约钉死)。

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

### Turn Pipeline (回合管线) (`services/engine-py/src/engine_py/run_agent.py`)

One conversational turn = one deep module. The public interface is `run_agent(job) -> dict`, and every entry scenario crosses this single seam: gateway chat dispatch, approval resumption (`job_resume_{approvalId}`), shadow replay (ADR-0007). Internally three sections, none of which are part of the interface:

- **Entry pre-assembly (入口预装配)**: greeting/onboarding bypass, image normalization, tenant-context injection, concurrent memory + RAG gathering.
- **Graph execution (图执行)**: the LangGraph DAG (triage → planner → merge → exec ⇄ validator → finish) with its two degradation arms (LLM circuit breaker / graph error → deterministic fallback).
- **Settle (收口)**: the post-graph persistence section — card synthesis → memory writes (assistant row, persona facts, episodic events) → task-memory plans → badcase signals → LLM token aggregation → session metrics. This is the internal seam's name; ADR-0007 and the wiring tests refer to it by this term.

### Temporal Workflow Layer — retired (ADR-0007)

The durable-execution route (`temporal/workflows.py` / `activities.py` / `worker.py`) was deleted on 2026-09-30: zero production starters existed, and its hand-copied settle wiring had already drifted from the pipeline. Periodic tasks (outbox reconcile / takeover release / badcase digest) now live in the gateway lifespan via `engine_py/scheduler.py`. Reintroducing durable execution in any shape requires a new ADR answering the two questions this retirement settled: who starts the workflows, and how the second copy of the settle wiring stays drift-free.

## Skills Subsystem (engine-py)

### Typed Skill Contract (`services/engine-py/src/engine_py/skills/contract.py`)
`SkillContext` / `SkillResult` are the sole interface between skills and their two production callers — the triage skill fast-track and the step executor dispatch are the two adapters that translate to/from the online camelCase dict once each (`to_dict()` shape frozen by `tests/test_skill_contract_golden.py`). Domain contexts (`guide_context` / `cart_context` / `order_context`) are fields, not key conventions: a concept like the per-turn cart additions (`cart_context.addedThisTurn`, consumed by the composite add-then-checkout scoped checkout) lives in one place instead of threading through five layers. `executor_node` returns `cart_context` upward (same dead-write fix as guideContext, 2026-09-12).

### Cart Action Table (`services/engine-py/src/engine_py/skills/cart/`)
CartManageSkill is a thin shell over `ACTION_TABLE` — verbs (checkout / order-bridge / view / delete / qty / vague-ask / add-all / add) are declarative rows (detector + handler); branch precedence is table order, not if-ladder. `resolver.py` is the single source for cart utterance regexes and `resolve_cart_item` (ordinal → name-match → lastModified → first) shared by delete/qty; `cards.py` owns cart_card assembly. The 920-line branch swamp this replaced produced the S6 wrong-order, phantom-Nike and dual-SKU dedup incidents.

### HITL Suspension Seam (`services/engine-py/src/engine_py/skills/suspension.py`)
`persist_suspended_plan` / `suspend_for_approval` are the only implementations of ticket creation + immediate plan persistence + response assembly (wayfinder 004: the recovery plan must hit TaskMemory the moment the approval ticket becomes visible to the 2s poller — the address-skill copy of this invariant used to sit after an unconditional `return` and never ran).

## Intent Data Flywheel Subsystem (engine-py)

### Labeling Faucet / 标注水龙头 (`services/engine-py/src/engine_py/triage/labeling.py`)

「谁有资格写 `intent_logs.actual_outcome`」的唯一事实点 —— silver label 三通道的资格谓词与回写 SQL 收敛于一个 module,三通道互补关系(①置信级联独占 `confidence_cascade` + 30 分钟窗,在线热路径、自管事务静默降级;②人审定性不限 method、借用调用方 session 与坏例状态同事务;③规则复判排除 `confidence_cascade` 批量贴)由此单点可查。铁律:**一次写入**(任何通道对已回填行零影响,资格谓词 IS NULL 门槛 + 回写时再验,先到先得);时间资格 Python 侧参数化(严禁 `NOW() - INTERVAL` PG-only 手写 SQL);全 ORM,严禁绕开本 module 手写 actual_outcome 回写 SQL。互斥契约由 `tests/test_outcome_labeling.py` 一册钉死(sqlite 密封);通道①端到端回归另见 `test_intent_outcome_backfill.py`(容器 DB)。消费方:在线侧 `IntentTriageEngine.backfill_clarify_outcome`(薄委托)、离线侧 `intent_flywheel/review_badcase.py` 与 `backfill_outcome_from_rules.py`(adapter)。

### intent_flywheel package (`services/engine-py/src/engine_py/intent_flywheel/`)

意图数据飞轮的包内 module 群,唯一入口 `python -m engine_py.intent_flywheel.<cli>`(backhaul_unanswered / export_intent_data / review_badcase / backfill_outcome_from_rules / gen_intent_cases / run_intent_eval / calibrate_semantic_routes 七件);`common.py` 持有 JSONL 读写(stdout 管道语义,`out` 为空或 `-` 打 stdout)与 CLI .env 装载(CWD → engine-py → 仓库根,setdefault 不覆盖)的唯一实现。测试面 = 常规 import(由 `tests/test_flywheel_importable.py` 钉死,sys.path 引导 hack 禁止回归)。评测集常量 `EVAL_CASES_PATH` 指向 `services/engine-py/evals/intent_cases.jsonl`(gen 写 / eval 读 / calibrate 可选输入)。训练轨(`scripts/training/`)为二步收编,随训练 artifacts 缝归位。
