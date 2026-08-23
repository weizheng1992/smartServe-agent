# Specification: Production Resiliency, Outbox Long-Transactions & Multi-Tenant Safety Sandbox

## Problem Statement

As the multi-tenant AI Customer Service platform scales to support concurrent business tenants (e.g., Nike, Adidas, Global Mall) and high-value transactional interventions, three critical architectural vulnerabilities threaten operational integrity:

1. **Dual-Write Ghost Approvals**: When an administrator approves a high-value refund or shipping address change ticket, a crash or network blip during workflow dispatch can leave the approval ticket marked as `approved` while the background execution job is never dispatched. This results in "ghost approved" tickets where customers never receive their refunds.
2. **Cross-Tenant Persona Context Contamination (IDOR)**: Long-term customer preferences and episodic memory are indexed purely by user identity without tenant scoping. When a single shopper chats with different tenant stores, brand-specific preferences (e.g., Nike shoe fits, exclusive coupons) risk bleeding into competing brand conversations (e.g., Adidas customer support).
3. **NL2SQL Security & Database Exhaustion Risk**: The natural language analytics compiler constructs dynamic SQL via string interpolation and simple character replacement. This poses potential SQL injection vulnerabilities under non-standard encodings, lacks database-level execution time fences, and fails to leverage PostgreSQL prepared statement plan reuse.

## Solution

A robust, enterprise-grade safety and resiliency framework that guarantees transactional consistency, strict multi-tenant context boundaries, and parameterized database query sandboxing:

1. **Transactional Outbox & Deterministic Idempotent Resumption**: Approval decisions and execution resume events are committed atomically in a single local database transaction. A fast-path synchronous dispatcher paired with an asynchronous reconciliation loop ensures that approved jobs are guaranteed to execute exactly once using deterministic `jobId` deduplication.
2. **Dual-Tier Scoped Persona Architecture**: Explicit separation of customer facts into `global` (physiological attributes, physical foot length, verified material allergies) and `tenant` (brand preferences, tenant-specific order habits). The context assembly pipeline strictly isolates retrieval to `Global + Current Tenant`.
3. **Parameterized AST Compiler & Read-Only Sandbox**: Complete refactoring of `NLMetricQueryEngine` to emit prepared statements with `$1`, `$2` parameter arrays and execute within isolated, read-only transactions guarded by mandatory 3-second statement timeouts and maximum row count boundaries.

## User Stories

1. As a platform administrator, I want approval status updates and workflow dispatch events to commit in the same atomic database transaction, so that system crashes never leave tickets in an approved-yet-unexecuted ghost state.
2. As a support supervisor, I want background reconciliation workers to automatically detect and retry any suspended jobs that failed to dispatch within 10 seconds, so that manual operational recovery is never required.
3. As a platform developer, I want resumption jobs to use deterministic identifiers derived from ticket IDs (`job_resume_${approvalId}`), so that concurrent retries never trigger duplicate financial refunds.
4. As an end user chatting with Nike support, I want my shoe size and general material allergies (global facts) to be remembered, so that I don't have to repeat my physical foot measurements across different stores.
5. As an end user chatting with Adidas support, I want my brand-specific Nike conversations to remain invisible to Adidas, so that my brand-specific interactions remain strictly confidential.
6. As a merchant tenant, I want customer long-term memories to be strictly partitioned by business scope, so that my competitor brands on the same SaaS platform cannot inspect my customer promotions or VIP tiers.
7. As an AI Profiler agent, I want automatic classification of extracted user facts into `global` and `tenant` scopes based on whether the fact represents an objective physical attribute or a brand-specific preference, so that memory partitioning requires no manual tagging.
8. As a store manager asking natural language BI queries, I want my queries to compile into parameterized PostgreSQL statements, so that my analytical questions are physically immune to SQL injection.
9. As a database administrator, I want all natural language analytics queries to execute within `SET TRANSACTION READ ONLY` sandboxes, so that AI-generated queries can never perform unintended data mutations or table deletions.
10. As a platform engineer, I want all natural language analytical queries to enforce a 3000ms statement timeout, so that broad historical scans or complex aggregations never exhaust database connection pools or degrade transactional order workloads.
11. As an API client, I want `NLMetricQueryEngine` to return structured `{ text: string, values: unknown[] }` objects, so that query execution utilizes PostgreSQL prepared query plan caching for faster response times.
12. As a customer service operator, I want the system to preserve suspended task plans without LLM re-planning upon human approval, so that the approved action executes deterministically with zero latency.
13. As an auditor, I want all outbox event state transitions and execution logs to be persisted in queryable database tables, so that every step of a financial approval can be traced end-to-end.
14. As an enterprise customer, I want tenant-specific data deletion requests (GDPR) to purge all tenant-scoped memory facts while preserving global account identity, so that privacy compliance is achieved with surgical precision.

## Implementation Decisions

### 1. Transactional Outbox Subsystem

- **Outbox Table Schema**: Introduce an `approval_outbox_events` table containing `id`, `approvalId`, `threadId`, `eventType` (`resume_execution`, `cancel_execution`, `reject_execution`), `payload`, `status` (`pending`, `processing`, `completed`, `failed`), `retryCount`, `createdAt`, and `updatedAt`.
- **Atomic Transition**: When `ApprovalGatekeeper.processApprovalAction` executes, the update to `pending_approvals` and the insert to `approval_outbox_events` run inside a single PostgreSQL database transaction.
- **Fast-Path & Background Loop**: The gatekeeper synchronously attempts `WorkflowOrchestrator.dispatchJob`. If it succeeds, the outbox event is immediately marked `completed`. If it fails or the process terminates, an asynchronous reconciliation worker polls for `pending` events older than 10 seconds and re-dispatches them with exponential backoff.
- **Deterministic Job Identifiers**: Resume jobs utilize deterministic job IDs formatted as `job_resume_${approvalId}` to ensure deduplication across Temporal and Redis singleflight locks.

### 2. Dual-Tier Scoped Persona Architecture

- **Database DDL Evolution**: Extend `long_memory_facts` and `episodic_events` with `business_id` (VARCHAR) and `scope` (VARCHAR, values: `'global'` | `'tenant'`).
- **Classifier Heuristics & Profiler Prompts**: Update the Profiler Agent prompt to tag objective physiological facts (shoe size in mm, fabric allergies, delivery carrier preference) as `scope: 'global'`, while tagging merchant-specific purchase loyalty, coupon codes, and brand discussions as `scope: 'tenant'` with `business_id`.
- **Scoped Retrieval in Context Assembly**: `ContextAssemblyPipeline` and `LongMemory.searchRelevantFacts` restrict recall queries to `WHERE user_id = $1 AND status = 'approved' AND (scope = 'global' OR business_id = $2)`.

### 3. Parameterized NL2SQL Compiler & Read-Only Execution Sandbox

- **CompiledSQL Interface**: `NLMetricQueryEngine.compile` returns a typed interface:
  ```typescript
  export interface CompiledSQL {
    text: string;
    values: unknown[];
  }
  ```
- **Positional Placeholder Generation**: Replaces literal string interpolation with positional parameters (`$1`, `$2`, `$3`...) for tenant ID, manager ID, filter field values, and pagination limit bounds.
- **Read-Only Transaction Sandbox Wrapper**: Encapsulates execution in a dedicated database helper:
  ```typescript
  export async function executeReadOnlyAnalyticsQuery<T>(
    compiled: CompiledSQL,
  ): Promise<T[]>;
  ```
  which opens a transaction, sets `SET TRANSACTION READ ONLY` and `SET LOCAL statement_timeout = '3000ms'`, binds `compiled.values`, and enforces an absolute pagination ceiling of 50 rows.

## Testing Decisions

- **Test Seams & Philosophy**: Tests must exercise public domain facades (`ApprovalGatekeeper`, `ContextAssemblyPipeline`, `NLMetricQueryEngine`) and assert observable business outcomes rather than internal private state.
- **Outbox & Crash Recovery Suite**:
  - Test seam: `ApprovalGatekeeper.processApprovalAction` followed by reconciliation worker trigger.
  - Verification: Simulate a network/dispatch failure after DB commit, trigger the reconciliation loop, and verify that the target task is successfully dispatched and outbox event marked `completed` with exactly-once execution.
- **Multi-Tenant Memory Isolation Suite**:
  - Test seam: `ContextAssemblyPipeline.assemble` and `LongMemory.extractAndStoreFact`.
  - Verification: Seed global facts (foot size 270mm) and tenant-specific facts for Nike (prefers Flyknit). Query context assembly under tenant `adidas` and verify that the global foot size is returned while Nike Flyknit preference is strictly omitted.
- **Parameterized SQL & Sandbox Injection Suite**:
  - Test seam: `NLMetricQueryEngine.compile` and read-only execution harness.
  - Verification: Provide adversarial inputs containing quote injections (`' OR 1=1; DROP TABLE products; --`) and verify that all inputs remain safely bound in `values` array without executing destructive DDL.

## Out of Scope

- Distributed consensus across multiple heterogeneous database engines (e.g., two-phase commit with external NoSQL databases).
- Real-time customer biometrics hardware integration.
- Custom user-defined SQL syntax extension plugins.

## Further Notes

- All database schema updates will use Drizzle ORM migration files generated via `bun drizzle-kit generate` and pushed via `bun drizzle-kit push`.
- Outbox workers will utilize Bun native timers and lightweight polling loops with zero external queue infrastructure dependencies.
