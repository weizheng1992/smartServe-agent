# Domain Context & Architectural Glossary

This document serves as the single source of truth for domain vocabulary and module shapes across the codebase.

## Execution & Gatekeeping Subsystem

### ApprovalGatekeeper (`packages/engine/src/approval/approvalGatekeeper.ts`)

A deep domain gatekeeper subsystem unifying security policy evaluation, pending approval lifecycle management, and execution resumption:

- **Security & Policy Rules**: Encapsulates double-refund checks against physical database status, refund auto-approval threshold evaluation against tenant business configs, and high-value shipping address change interception.
- **Ticket Lifecycle & Concurrency**: Manages pending ticket creation (`waiting`), timeout auto-expiration (`expired`), distributed Redis SETNX / In-Memory mutual exclusion locks, and決议状态机迁移 (`approved`, `rejected`, `cancelled`, `resolved_by_human`).
- **Resumption & IM Takeover**: Dispatches instant human IM takeover notifications and resumes suspended LangGraph Agent executions via `WorkflowOrchestrator.dispatchJob`.

### AgentMemoryEngine (`packages/engine/src/memory/agentMemoryEngine.ts`)

A unified 4-tier memory facade that encapsulates `ShortMemory`, `LongMemory`, `TaskMemory`, and `EpisodicMemory`:

- **Atomic Multi-Tier Gathering (`gatherContext`)**: Parallelly fetches sliding conversation history, approved long-term facts, task state, and episodic events in a single call.
- **Turn Recording (`recordTurn`)**: Structured, non-blocking turn persistence across short messages, profile facts, task plans, and episodic events.

### ContextAssemblyPipeline (`packages/engine/src/memory/contextAssemblyPipeline.ts`)

A deep context assembly and token budgeting engine:

- **Structured Context Bundling**: Assembles sliding short memory history, RAG knowledge slices, long-term customer persona facts, and episodic memory into structured prompt sections.
- **Relevance & Token Budget Pruning**: Dynamically prunes facts and history based on confidence and target token budgets.

### NLMetricQueryEngine (`packages/tools/src/nlQuery/nlMetricQueryEngine.ts`)

A deep, consolidated Natural Language to SQL analytics compiler engine:

- **Orthogonal AST Parsing**: Normalizes customer colloquialisms, extracts time windows (`TimeRangeResult`), resolves dimensions and group-by columns, parses dynamic value/category filters, and determines top-N / order directions.
- **Parameterized SQL Compilation**: Safely compiles ASTs into PostgreSQL physical queries respecting multi-tenant boundaries (`business_id`) and store manager scopes without risking SQL injection.

### StepExecutionEngine

A deep module facade that orchestrates the execution of individual task plan subtasks. It encapsulates:

- Fast-path tool matching and LLM tool parameter extraction
- Delegation to the `ApprovalPolicyEngine` for security and financial gatekeeping
- Tool execution dispatching and result logging
- User-friendly localized event emission

### ApprovalPolicyEngine

A domain security gatekeeper enforcing financial safety rules and human-in-the-loop (HITL) policy checks:

- **Double-Refund Prevention**: Checks database status to block duplicate refunds on already-refunded orders.
- **Auto-Approval Thresholding**: Automatically approves refunds below tenant limits (default $100) without human intervention.
- **High-Value Address Modification Gate**: Intercepts address changes on high-value orders ($100+) for human approval.
- **Approval Ticket Lifecycle & Deadline Timeout**: Manages pending approval ticket states (`waiting`, `approved`, `rejected`, `cancelled`, `expired`) and auto-expires tickets past their 24-hour deadline.

### ExecutionOutcome

An immutable result domain object returned by the execution engine, containing:

- Updated task plan (`nextPlan`)
- Status (`completed`, `pending`, `failed`)
- Execution result payload or error description
- Transition/error counter increments

## Database & Persistence Subsystem

### FakePool Simulator (`fakePool.ts`)

A standalone in-memory SQL database emulator that intercepts PostgreSQL queries during offline/testing modes. It simulates 12+ relational tables (`users`, `threads`, `orders`, `products`, `messages`, `pending_approvals`, etc.) without requiring a live PostgreSQL connection.

### Domain Repositories (`packages/db/src/repositories/`)

Strongly typed domain repositories that decouple application nodes and HTTP API routes from raw database query strings:

- `IUserRepository`: User account resolution and registration (`findOrCreateUserByEmail`).
- `IThreadRepository`: Session thread lifecycle, multi-tenant isolation, and atomic cascade deletions (`getUserThreads`, `createThread`, `deleteThread`).
- `IMessageRepository`: Conversational message history persistence and ordering (`getMessages`, `addMessage`).
- `IOrderRepository`: Multi-tenant order status and logistics details lookup (`getOrder`).

## RAG Knowledge Subsystem

### KnowledgeEngine (`packages/engine/src/rag/knowledgeEngine.ts`)

A unified deep module facade class for all RAG operations across multi-tenant knowledge bases:

- **Hybrid Retrieval (`search`)**: Multi-tenant safe search combining Cosine Vector similarity, Portable BM25 keyword matching, Reciprocal Rank Fusion (RRF k=60), and hybridScore >= 0.40 circuit breaker cutoff.
- **Atomic File Hot Replacement (`replaceFile`)**: Deletes stale file chunks by source URL and re-ingests updated Markdown AST chunks, Anthropic Contextual Summaries, and vector embeddings in a single atomic pass.
- **Granular Chunk Maintenance (`upsertChunk` & `deleteSource`)**: Direct single-chunk upserts and file-level physical cleanup.
- **Directory Ingestion (`ingestDirectory`)**: Parallel directory parsing for Frontmatter headers (`businessId`, `category`, `title`) and LLM zero-shot category classification.

## API & Service Layer Subsystem

### ChatSessionOrchestrator (`apps/web/app/api/chat/services/chatSessionOrchestrator.ts`)

A deep domain service that decouples chat session initiation, concurrency control, human support detection, and SSE streaming from HTTP route handlers:

- **Tenant Quota Guard Enforcement**: Verifies rate limits and token usage bounds before processing requests.
- **Human Support Session Bypass**: Intercepts queries when an active human takeover (`waiting`) ticket exists and routes messages directly to persistence without triggering AI Agent graph execution.
- **Request Collapsing & Deduplication**: Employs singleflight request collapsing for in-flight queries and 5-second exact text hash deduplication caching.
- **Execution Engine Dispatching**: Seamlessly dispatches work to Temporal workflow orchestration or falls back to local LangGraph state graph.
- **Unified SSE Event Streaming (`createEventStream`)**: Encapsulates Temporal polling loops, LangGraph event journal playback, and heartbeat keepalive frames for client streams.

### ApprovalService (`apps/web/app/api/chat/services/approvalService.ts`)

A domain service that manages human-in-the-loop (HITL) approval ticket lifecycles and human agent IM sessions:

- **Pending Ticket Querying**: Retrieves pending approvals joined with business tenant metadata.
- **IM Human Support Takeover**: Initiates instant human takeover (`start_human_takeover`) and records system notifications into conversation history.
- **Concurrency & Lock Control**: Coordinates distributed Redis SETNX locking with memory fallback sets to prevent double-submit collisions.
- **Agent Resumption Dispatching**: Atomically transitions approval ticket statuses (`approved`, `cancelled`, `rejected`, `resolved_by_human`) and resumes suspended LangGraph Agent executions with context prompts.

### AgentStreamClient (`apps/web/app/home/utils/agentStreamClient.ts`)

A dedicated SSE network stream client that decouples EventSource transport, event parsing, and localized node name mapping from React UI hooks:

- **EventSource Transport Management**: Handles SSE connection establishment, event listener binding, and safe resource cleanup.
- **Typed Event Dispatching**: Emits structured status, result, and error events to UI subscribers (`onStatus`, `onResult`, `onError`).

### WorkflowOrchestrator (`packages/engine/src/orchestrator/workflowOrchestrator.ts`)

A unified execution orchestrator and fallback defense layer encapsulating Temporal workflow dispatching and local LangGraph simulation:

- **Adaptive Execution Routing (`dispatchJob`)**: Probes Temporal Server connectivity and dynamically routes tasks to Temporal durable workflows or falls back to local high-fidelity LangGraph simulators.
- **Serverless Anti-Freeze & Promise Tracking**: Automatically binds execution promises to Serverless request context (`waitUntil`) and global execution tracking maps (`getJobExecution`).
