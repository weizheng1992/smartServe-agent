# 🌐 smartServe: Enterprise-Grade Customer Support Agent Platform
## 🏛️ Comprehensive Architecture, Subsystem Design, and Relational Database Blueprint

This document outlines the end-to-end system design and architectural blueprint for **smartServe**, an enterprise-ready, multi-tenant customer support platform. 

It transitions the current single-merchant, monolithic Agent structure into a highly scalable **Supervisor-Worker Multi-Agent Architecture** backed by **Temporal distributed child workflows**, **Redis distributed idempotency locking**, **PostgreSQL multi-tenant logical isolation**, and **modular RAG evaluation**.

---

## 📅 System Architecture Blueprint

```
                      +------------------------------------------+
                      |         Tenant Console Dashboard         |
                      |  (Configs, Prompts, Knowledgebase, BI)   |
                      +--------------------+---------------------+
                                           |
                                           v
+-------------------------+   +------------+------------+   +--------------------------+
|  User Embedded Widget   |   |   SaaS Config Engine   |   |    Human Audit Desk      |
| (F12 secure thread, v4) +-->+ (Tenant VPC Isolation)  +<--+ (Non-blocking HITL Desk) |
+------------+------------+   +------------+------------+   +------------+-------------+
             |                             |                             |
             |                             v                             |
             |                +------------+------------+                |
             +--------------->|   Supervisor / Router   |<---------------+
                              |    (Triage & Routing)   |
                              +------+-----------+------+
                                     |           |
             +-----------------------+           +-----------------------+
             | (Logistics Route)                                         | (Financial Route)
             v                                                           v
+------------+------------+                                 +------------+-------------+
| Logistics Sub-Agent     |                                 |   Financial Sub-Agent    |
| (getOrderStatus, list)  |                                 | (processRefund, Invoice) |
+------------+------------+                                 +------------+-------------+
             |                                                           |
             +-----------------------+           +-----------------------+
                                     |           |
                                     v           v
                              +------+-----------+------+
                              |    Validator Node       |
                              | (LLM-as-a-Judge, Rep)   |
                              +------------+------------+
                                           |
                                           v
                              +------------+------------+
                              |      Finish Node        |
                              | (Contextual RAG, APM)   |
                              +-------------------------+
```

---

## 1. Core Architectural Pillars

### 1.1 Tenant Portal & Multi-Merchant Isolation
*   **Design**: Each merchant represents a distinct `business_id` (e.g. `nike`, `adidas`, `puma`). 
*   **Logical Isolation**: All SQL queries targeting RAG documents, users, threads, orders, and products are strictly bound by parameterized filters: `WHERE business_id = $1`.
*   **Dynamic Policy Thermal Reload**: Merchant-specific configurations, system prompts, refund limits, and tool permissions are retrieved dynamically on every transaction thread. This enables hot-swapping brand settings without system downtime.

### 1.2 User Embedded Widget & Secure Sessions
*   **Session Initialization**: Upon first entry, the browser widget issues a secure `crypto.randomUUID()` threadId. No static defaults (such as `thread_local_shared`) are allowed.
*   **URL Address-Bar Sync**: The thread ID is dynamically bound to the address bar query string (`?threadId=...`) using `window.history.replaceState`. Refreshing, bookmarking, or sharing the URL perfectly recovers the state.
*   **Asymmetric UUID Mapping**: To satisfy type constraints on relational databases, user-provided string IDs (e.g. `'u_default_id'`) are mapped deterministically via md5 hashing to valid UUIDs (`'21f7d08d-a7c4-a48e-bb1a-cd5b04564555'`) and ensured inside the physical table, preventing database crashes.

### 1.3 Supervisor-Worker Multi-Agent Orchestrator
*   **Supervisor (The Triage Total Bus)**: Classifies customer requests. Rather than feeding all 20+ tool schemas to a single model, the Supervisor routes the conversation payload to a dedicated, high-relevance domain expert.
*   **Logistics Sub-Agent (Logistics Worker)**: Dedicated to tracking and listing orders. Handles `getOrderStatus` and `listUserOrders`.
*   **Financial Sub-Agent (Financial Worker)**: Isolated in a highly secure VPC partition. Handles `processRefund` and `generateInvoice`.
*   **LangGraph Subgraphs (Single-Engine Mode)**: Local and sandboxed execution compiles these sub-agents as nested sub-graphs within the main state machine, preserving sub-state contexts.
*   **Temporal Child Workflows (Distributed Production Mode)**: In high-concurrency production deployments, the Supervisor workflow spawns isolated **Child Workflows** targeting distinct, physical **Temporal Task Queues** (e.g. `'financial-task-queue'`), preventing general-access servers from touching financial processing.

### 1.4 Non-blocking Asynchronous Human-in-the-Loop (HITL) Desk
*   **Stateless Suspension**: When an action crosses a security limit (such as refunding an order over the merchant's limit), the Agent transitions the step to `'waiting_approval'` and registers a pending approval inside `pending_approvals`.
*   **Process Liberation**: Rather than holding active HTTP long-polls or locking Web Socket connections, the execution process **immediately terminates**, freeing 100% of CPU and socket handles.
*   **Resurrection on Signal**: When the administrator clicks "Approve" or "Reject", a POST endpoint receives the payload, restores the exact thread context from PostgreSQL, and resumes the StateGraph / Temporal execution.
*   **Stuck-Task Healing Sweeper**: An automated background daemon scans and transitions stuck or expired approvals to `'expired'` after 30 minutes, writing back to the chat history to inform the customer and prevent hanging state leakages.

### 1.5 Real-time Cost Telemetry & Dual-Layer RAG Evaluator
*   **SaaS APM & Cost Accounting**: Granularly tracks input, output, and total token usage for every LLM transaction. Costs are dynamically calculated using merchant-specific rate maps and written to `session_metrics` to provide instant analytics on the tenant BI dashboard.
*   **RAG Precision & Recall Evaluation**: Split into two distinct layers:
    *   *Retrieval Layer*: Evaluates retrieval accuracy using promptfoo's `context-relevance` scorer to ensure only highly relevant brand chunks are pulled.
    *   *Generation Layer*: Assesses output faithfulness via `context-faithfulness` and `answer-relevance` to prevent the model from generating information outside the retrieved contexts.
*   **Out-of-Domain Anti-Hallucination Assertions**: Customized test suites ensure that when the user asks questions outside the knowledge base (e.g., asking about Bitcoin payments), the Agent gracefully declines rather than hallucinating fake policies.

---

## 2. PostgreSQL Relational Database Schema Blueprint

```sql
-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =========================================================================
-- 1. SaaS Multi-Tenant & Configuration Schema
-- =========================================================================

CREATE TABLE IF NOT EXISTS business_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id VARCHAR(50) UNIQUE NOT NULL,
    config JSONB NOT NULL, -- {systemPrompt, intents, tools, refundAutoApprovalLimit, confidenceThresholds}
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =========================================================================
-- 2. Core User & Conversational Schema
-- =========================================================================

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS threads (
    id VARCHAR(100) PRIMARY KEY, -- Maps to browser threadId (v4 UUID string)
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    business_id VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'active', -- 'active' | 'completed' | 'abandoned'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id VARCHAR(100) PRIMARY KEY,
    thread_id VARCHAR(100) REFERENCES threads(id) ON DELETE CASCADE NOT NULL,
    role VARCHAR(20) NOT NULL, -- 'user' | 'assistant' | 'system'
    content TEXT NOT NULL,
    timestamp VARCHAR(50) NOT NULL -- ISO 8601 string
);

-- =========================================================================
-- 3. Business E-Commerce Transactional Schema
-- =========================================================================

CREATE TABLE IF NOT EXISTS products (
    id VARCHAR(100) PRIMARY KEY,
    business_id VARCHAR(50) NOT NULL, -- Isolated tenant goods catalog
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price REAL NOT NULL,
    stock INTEGER DEFAULT 99,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(100) PRIMARY KEY, -- e.g. 'ORD-98712'
    user_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    business_id VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL, -- 'shipped' | 'delivered' | 'refunded'
    carrier VARCHAR(100) NOT NULL, -- 'FedEx' | 'SF Express'
    tracking_number VARCHAR(100) NOT NULL,
    estimated_delivery VARCHAR(50) NOT NULL,
    total_amount REAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_items (
    id VARCHAR(100) PRIMARY KEY,
    order_id VARCHAR(100) REFERENCES orders(order_id) ON DELETE CASCADE NOT NULL,
    product_id VARCHAR(100) REFERENCES products(id) ON DELETE RESTRICT NOT NULL,
    quantity INTEGER NOT NULL,
    price_at_purchase REAL NOT NULL
);

-- =========================================================================
-- 4. Human Audit & Asynchronous Approvals Schema
-- =========================================================================

CREATE TABLE IF NOT EXISTS pending_approvals (
    id VARCHAR(100) PRIMARY KEY, -- UUID string
    thread_id VARCHAR(100) REFERENCES threads(id) ON DELETE CASCADE NOT NULL,
    action_type VARCHAR(50) NOT NULL, -- 'refund' | 'address_change'
    action_payload JSONB NOT NULL, -- Arguments needed to execute upon approval
    status VARCHAR(20) DEFAULT 'waiting', -- 'waiting' | 'approved' | 'rejected' | 'expired'
    deadline TIMESTAMP WITH TIME ZONE NOT NULL, -- Deadline for background sweepers
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =========================================================================
-- 5. Contextual RAG & Vector Knowledgebase Schema
-- =========================================================================

CREATE TABLE IF NOT EXISTS rag_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id VARCHAR(50) NOT NULL,
    source_url VARCHAR(255),
    chunk_text TEXT NOT NULL,
    contextual_summary TEXT, -- Augmented chunk contextual summary
    embedding TEXT, -- Serialized float vector
    metadata JSONB, -- {category, version, ...}
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS rag_business_idx ON rag_documents(business_id);

-- =========================================================================
-- 6. Conversational APM & Financial Telemetry Schema
-- =========================================================================

CREATE TABLE IF NOT EXISTS session_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id VARCHAR(50) NOT NULL,
    thread_id VARCHAR(100) REFERENCES threads(id) ON DELETE CASCADE NOT NULL,
    total_tokens INTEGER DEFAULT 0,
    calculated_cost_usd REAL DEFAULT 0.0,
    node_transitions_count INTEGER DEFAULT 1,
    resolution_status VARCHAR(50) NOT NULL, -- 'resolved_auto' | 'waiting_approval' | 'expired' | 'cancelled'
    avg_latency_ms REAL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id VARCHAR(50) NOT NULL,
    git_commit VARCHAR(100),
    avg_answer_quality REAL,
    avg_latency_ms REAL,
    total_cost_usd REAL,
    pass_rate REAL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS eval_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES eval_runs(id) ON DELETE CASCADE NOT NULL,
    case_name VARCHAR(255) NOT NULL,
    passed BOOLEAN,
    metrics JSONB -- {toolAccuracy, answerQuality, latency, cost}
);
```

---

## 3. Implementation and Evolution Roadmap

### 3.1 Phase 1: Establish Supervisor-Worker Router & Subgraphs
1.  **Refactor Triage**: Upgrade the triage node to output a routing decision identifying target domains (`logistics` or `financial`).
2.  **Define Sub-Agents**: Isolate prompt files and build secondary `StateGraph` configurations for logistics (carrying `getOrderStatus` and `listUserOrders`) and finance (carrying `processRefund` and `generateInvoice`).
3.  **Compile Subgraphs**: Connect the sub-agents into the parent `buildAgentGraph` using LangGraph conditional routing hooks.

### 3.2 Phase 2: Distributed Idempotency Locks
1.  **Integrate Redis SETNX**: Bind request entry-points to Redis locks with short TTLs (e.g., 5 seconds) to collapse duplicate and concurrent user submissions.
2.  **Cluster Safety**: Ensure lock evaluation is cluster-safe to block racing requests across multiple application pods or serverless instances.

### 3.3 Phase 3: Hardened Database Integration
1.  **Parametrize all SQL**: Scan and refactor all tools and API SQL execution queries using parameterized positional parameters (`$1`, `$2`), eliminating string formatting.
2.  **Asymmetric Session Cleanup**: Ensure thread validation mapping functions gracefully resolve custom string keys into matching system users without generating database key mismatches.

### 3.4 Phase 4: Non-Blocking HITL Desk & Cleanup Sweepers
1.  **Decouple Execution Sockets**: Ensure the Next.js API disconnects HTTP and socket connections immediately after writing states to `pending_approvals`.
2.  **Automate Stuck Sweep**: Deploy background tasks or cron triggers to scan, transition, and log notifications inside PostgreSQL when pending tasks exceed expirations.

### 3.5 Phase 5: Continuous APM & RAG Regression Dashboards
1.  **Log Token Costs**: Aggregate token measurements per execution and persist calculations into `session_metrics` for real-time cost-of-service insights.
2.  **Automated Quality Runs**: Embed `promptfoo eval` runs within the CI/CD deployment flow to protect RAG precision and enforce zero-hallucination guardrails before production releases.
