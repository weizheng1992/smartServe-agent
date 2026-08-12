# 🚀 smartServe-agent: 分布式多租户 SaaS 智能客服决策中台平台

smartServe-agent 是一款基于 **Turborepo Monorepo**、**Bun 运行环境** 与 **LangGraph 决策图** 构建的日活千万级、高弹性、高防卫金融级智能客服 Agent 决策平台。

系统原生支持 **SaaS 多租户物理隔离**、**人工核签红线拦截与重规划自适应回溯**、**Anthropic Contextual RAG（上下文增益知识库检索）**，并配备了 **Redis 分布式并发锁**、**物理自愈指数退避 LLM HA-Proxy**、以及**高敏捷 SaaS 财务算力账单仪表盘**。

在近期，我们对整个系统进行了大规模的**高深度门面（Deep Module Facade）重构与稳定性加固**，将执行引擎、数据库仿真器、RAG 知识库、API 路由层、四层记忆以及网络流调度彻底拆解为高内聚、易测试的深度领域模块。

---

## 目录

1. [项目架构与双模引擎设计](#1-项目架构与双模引擎设计)
2. [高精准工作空间目录树 (Workspace Tree)](#2-高精准工作空间目录树-workspace-tree)
3. [核心模块深度技术讲解 (Deep Module Breakdown)](#3-核心模块深度技术讲解-deep-module-breakdown)
   - [3.1 `apps/web` 前端可视化与 API 服务层](#31-appsweb-前端可视化与-api-服务层)
   - [3.2 `packages/engine` 核心 Agent 智能决策图与调度引擎](#32-packagesengine-核心-agent-智能决策图与调度引擎)
   - [3.3 `packages/db` 关系型范式数据接入与领域仓储](#33-packagesdb-关系型范式数据接入与领域仓储)
   - [3.4 `packages/tools` 物理工具链与安全防护拦截](#34-packagestools-物理工具链与安全防护拦截)
   - [3.5 `packages/observability` 算力计量与全链路 Trace 日志](#35-packagesobservability-算力计量与全链路-trace-日志)
   - [3.6 `packages/business-configs` 多商户 SaaS 动态策略配置](#36-packagesbusiness-configs-多商户-saas-动态策略配置)
4. [核心底层深度设计实现细节](#4-核心底层深度设计实现细节)
   - [4.1 任务执行与安控网关 (`StepExecutionEngine` & `ApprovalPolicyEngine`)](#41-任务执行与安控网关-stepexecutionengine--approvalpolicyengine)
   - [4.2 统一四层记忆高深度门面 (`AgentMemoryEngine`)](#42-统一四层记忆高深度门面-agentmemoryengine)
   - [4.3 统一 RAG 知识库门面 (`KnowledgeEngine`)](#43-统一-rag-知识库门面-knowledgeengine)
   - [4.4 领域服务与 API 控制器解耦 (`ChatSessionService` & `ApprovalService`)](#44-领域服务与-api-控制器解耦-chatsessionservice--approvalservice)
   - [4.5 工作流调度与本地模拟器统一 (`WorkflowOrchestrator`)](#45-工作流调度与本地模拟器统一-workfloworchestrator)
   - [4.6 实时 SSE 长连接客户端 (`AgentStreamClient`)](#46-实时-sse-长连接客户端-agentstreamclient)
   - [4.7 金融级人机协同与认知回溯决策环 (HITL)](#47-金融级人机协同与认知回溯决策环-hitl)
   - [4.8 SaaS 级多租户隔离与 Contextual RAG 检索](#48-saas-级多租户隔离与-contextual-rag-检索)
   - [4.9 物理工具链政策红线守卫 (SOP Guardrail)](#49-物理工具链政策红线守卫-sop-guardrail)
   - [4.10 双通道并发防刷与 Redis SETNX 分布式锁](#410-双通道并发防刷与-redis-setnx-分布式锁)
   - [4.11 SaaS 算力审计与财务账单度量系统](#411-saas-算力审计与财务账单度量系统)
5. [质量保障与评测体系 (Testing & Tooling)](#5-质量保障与评测体系-testing--tooling)
6. [开发与部署命令](#6-开发与部署命令)
7. [生产上线前 SOP 流程 (Pre-Launch Checklist)](#7-生产上线前-sop-流程-pre-launch-checklist)
   - [7.1 基础设施与环境验证 (Environment & Infrastructure Setup)](#71-基础设施与环境验证-environment--infrastructure-setup)
   - [7.2 安全防护与密钥脱敏 Check (Security & Secrets Management)](#72-安全防护与密钥脱敏-check-security--secrets-management)
   - [7.3 质量验证与自动化测试全覆盖 (Automated Testing & Quality Gate)](#73-质量验证与自动化测试全覆盖-automated-testing--quality-gate)
   - [7.4 高并发性能压测 (High-Concurrency Load Testing)](#74-高并发性能压测-high-concurrency-load-testing)
   - [7.5 熔断与配额防暴刷机制验证 (Circuit Breaker & Quota Guard)](#75-熔断与配额防暴刷机制验证-circuit-breaker--quota-guard)
   - [7.6 可观测性与健康检查 (Observability & Health Checks)](#76-可观测性与健康检查-observability--health-checks)

---

## 1. 项目架构与双模引擎设计

平台采用 **双模弹性执行引擎** 设计，兼具高灵活性与极致抗灾灾备能力：

```
┌─────────────────────────────────┐
│     Next.js Web (apps/web)      │ ← 前端UI + AgentStreamClient SSE 订阅流
└────────────────┬────────────────┘
                 │
        POST /api/chat 提交 (由 ChatSessionService 承接 Quota Guard、Singleflight 与人工接管)
                 │
                 ▼
     [ WorkflowOrchestrator 调度 ]
                 ├───────────────────────────────────────┐
                 │ (未连接/Offline)                       │ (物理连接成功/Online)
                 ▼                                       ▼
┌─────────────────────────────────┐    ┌─────────────────────────────────┐
│     本地极速直跑仿真模式         │    │       生产级 Temporal 引擎       │
│  - 零时开销直接启动 StateGraph   │    │  - 注册为 agentWorkflow 工作流   │
│  - 使用 EventEmitter 进行日志广播│    │  - 状态物理入库，支持 Queries 检索│
│  - 由 Orchestrator 跟踪 Promise  │    │  - 调起物理活动 (Activities) 节点 │
└────────────────┬────────────────┘    └────────────────┬────────────────┘
                 │                                       │
                 └──────────────────┬────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        核心 Agent 状态机决策图                         │
│   triage(分流) ──→ planner(规划) ──→ merge(合并) ──→ executor(执行工具) │
│     │                 ▲                                   │            │
│     │                 └───────────────── validator(校验) ◄┘            │
│     ▼                                                                  │
│   finish(终点合成回复，依据真实物理 RAG 和工具数据提炼答复)                  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        数据持久化与二级缓存层                         │
│  - PostgreSQL / Drizzle ORM (Domain Repositories & FakePool 离线关系型仿真) │
│  - Redis 物理分布式缓存 (含 localLocks 内存降级锁保护与 DEL 缓存自洁)    │
│  - session_metrics 财务度量表 (毫秒级高精度决策时效 & Token 成本统计)     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 高精准工作空间目录树 (Workspace Tree)

本仓库采用 Turborepo Monorepo 进行组织管理，严格隔离了应用端（`apps/`）与底层公共基础设施包（`packages/`）：

```
.
├── apps/
│   ├── web/                         # Next.js 15 主站用户聊天与客服交互系统 (3000 端口)
│   │   ├── app/                     # App Router 核心路由
│   │   │   ├── api/                 # 服务端 API 接口层 (轻量 Controller 层)
│   │   │   │   ├── analytics/       # SaaS 财务算力 / BI 大盘统计端点
│   │   │   │   ├── auth/login/      # 多商户隔离登录鉴权 API
│   │   │   │   ├── chat/            # 智能对话核心路由 (ChatSessionService & ApprovalService 领域服务)
│   │   │   │   │   ├── approvals/   # 人工审核工单决策 API 控制器
│   │   │   │   │   ├── services/    # ChatSessionService & ApprovalService 领域服务层
│   │   │   │   │   └── route.ts     # 接收对话请求分发中转控制器
│   │   │   │   ├── chat/[jobId]/stream/ # SSE 实时状态机节点日志广播管道
│   │   │   │   └── health/          # 系统健康检查轮询探针
│   │   │   ├── home/                # 核心控制台面板
│   │   │   │   ├── components/      # ChatArea, APMPanel, LeftSidebar, AuditDesk
│   │   │   │   ├── hooks/           # useChatMessages (基于 AgentStreamClient), useChatThreads
│   │   │   │   └── utils/           # AgentStreamClient (SSE 订阅客户端) & translateTaskPlan
│   │   │   ├── login/               # 商户登录界面
│   │   │   └── page.tsx             # 客服核心交互大屏入口
│   │   ├── components/              # 登录与通用组件
│   │   ├── e2e/                     # Playwright 端到端 UI 自动化测试
│   │   └── package.json
│   │
│   └── admin/                       # 商户/系统级人工核签中台大屏 (3001 端口)
│       ├── app/                     # App Router 路由结构
│       │   └── home/                # 工单流转与人工接管控制台
│       └── package.json
│
├── packages/
│   ├── engine/                      # 核心 Agent 决策图与分布式工作流 (LangGraph + Temporal)
│   │   ├── src/
│   │   │   ├── graph/               # 决策图定义与节点
│   │   │   │   ├── nodes/           # StepExecutionEngine, ApprovalPolicyEngine, triage, planner, validator, finish
│   │   │   │   ├── eventEmitter.ts  # 本地直跑事件广播器
│   │   │   │   └── buildGraph.ts    # 编译 LangGraph 并集成死循环物理熔断器
│   │   │   ├── memory/              # AgentMemoryEngine 统一 4 重多维度状态记忆门面
│   │   │   │   ├── agentMemoryEngine.ts # 统一 4 层记忆并行拉取与归档门面
│   │   │   │   ├── shortMemory.ts   # 短期对话历史记忆
│   │   │   │   ├── longMemory.ts    # 长期事实卡片提取与向量记忆
│   │   │   │   ├── episodicMemory.ts# 真实情境回忆事件记忆
│   │   │   │   └── taskMemory.ts    # 物理 Task Plan 状态持久化层
│   │   │   ├── rag/                 # KnowledgeEngine 统一 RAG 知识库门面
│   │   │   │   ├── knowledgeEngine.ts # 混合检索、文件热替换、单切片维护与目录入库门面
│   │   │   │   └── contextualRag.ts # Anthropic Contextual RAG 混合检索引擎
│   │   │   ├── orchestrator/        # WorkflowOrchestrator 统一工作流调度与降级防御层
│   │   │   │   └── workflowOrchestrator.ts # 统一 Temporal 工作流与本地 LangGraph 调度
│   │   │   ├── llm/                 # LLM 自愈重试与 CircuitBreaker 断路器
│   │   │   └── temporal/            # 分布式工作流编排 (client, worker, workflows, activities)
│   │   └── tests/                   # 46+ 全量单元与集成测试
│   │
│   ├── db/                          # 关系型范式数据层 (Drizzle ORM & Domain Repositories)
│   │   ├── drizzle/                 # 数据库 Migration 自动生成 SQL
│   │   └── src/
│   │       ├── repositories/        # 强类型领域仓储接口 (IUserRepository, IThreadRepository, IMessageRepository, IOrderRepository)
│   │       ├── client.ts            # Drizzle PostgreSQL 连接客户端
│   │       ├── fakePool.ts          # 隔离的 FakePool 高保真离线仿真关系型数据库
│   │       ├── schema.ts            # 3NF 物理表定义
│   │       └── seed.ts              # 种子数据与租户策略灌入脚本
│   │
│   ├── tools/                       # 物理工具链与安全红线拦截器 (ecommerce, screenshot, registry)
│   ├── observability/               # 财务度量分析与 APM Trace 观测包 (Langfuse, Pino Logger, metrics)
│   ├── business-configs/            # SaaS 多商户动态 JSON 策略配置 (ecommerce.config.ts)
│   ├── types/                       # 全局强类型定义共享包 (agent, approval, config, db, event, observability, tool)
│   └── ui/                          # 共享 UI 组件库与基础样式包 (Tailwind, Lucide Icons, Shadcn utils)
│
├── CONTEXT.md                       # 领域上下文与深度模块规范名词表
├── CLAUDE.md                        # Claude Code 开发 SOP 指南
└── README.md                        # 系统主干指南自述文档
```

---

## 3. 核心模块深度技术讲解 (Deep Module Breakdown)

### 3.1 `apps/web` 前端可视化与 API 服务层

- **职责范围**: 承载客服前端对话窗口、AI 智能子任务 DAG 状态实时展示，并提供解耦的 API 领域服务层。
- **核心模块**:
  - `apps/web/app/api/chat/services/chatSessionService.ts`: 承接会话启动、配额校验（`checkTenantQuotaGuard`）、人工客服接管拦截、`Singleflight` 并发请求合并及短 TTL 缓存。
  - `apps/web/app/api/chat/services/approvalService.ts`: 负责人工工单查询、客服主动 IM 接管、分布式锁（Redis SETNX + 内存降级锁）与 Agent 恢复调度。
  - `apps/web/app/home/utils/agentStreamClient.ts`: 专门负责 EventSource 建立、心跳保持、 typed 事件派发及安全回收。

### 3.2 `packages/engine` 核心 Agent 智能决策图与调度引擎

- **职责范围**: Agent 大脑决策中枢，集成 LangGraph 状态图、Temporal 分布式工作流、RAG 向量混合检索与重排。
- **核心模块**:
  - `StepExecutionEngine`: 封装快速通道匹配、参数提取、策略评估与工具派发；
  - `ApprovalPolicyEngine`: 封装双重退款拦截、免签额度评估、高价值地址变更校验与超时解挂；
  - `AgentMemoryEngine`: 统一调度短期、长期、任务与情境四层记忆；
  - `KnowledgeEngine`: 提供 SaaS 隔离混合检索、原子级文件热替换与目录入库；
  - `WorkflowOrchestrator`: 统一调度 Temporal 生产工作流与本地 LangGraph 模拟器。

### 3.3 `packages/db` 关系型范式数据接入与领域仓储

- **职责范围**: 关系型数据持久化与离线仿真器。
- **核心模块**:
  - `fakePool.ts`: 独立隔离的 12+ 张表的内存关系型数据库仿真器；
  - `packages/db/src/repositories/`: 提供强类型领域仓储接口（`IUserRepository`, `IThreadRepository`, `IMessageRepository`, `IOrderRepository`），实现真实 PG 驱动与 FakePool 仿真的无缝解耦。

---

## 4. 核心底层深度设计实现细节

### 4.1 任务执行与安控网关 (`StepExecutionEngine` & `ApprovalPolicyEngine`)

- **`StepExecutionEngine`**：将原本 800+ 行的单体 `executor.node.ts` 拆解为高深度门面，隐去工具参数匹配、Fast-Path 旁路、安控策略校验与工具调起的复杂度。
- **`ApprovalPolicyEngine`**：集中管理金融安全红线：
  - 双重退款防刷（`checkDoubleRefund`）；
  - 租户动态免签限额（`evaluateRefundAutoApproval`）；
  - 高价值订单地址修改门禁（`evaluateAddressChangePolicy`）；
  - 24 小时工单超时自动解挂（`evaluatePendingApprovalState`）。

### 4.2 统一四层记忆高深度门面 (`AgentMemoryEngine`)

- **原子化并发拉取 (`gatherContext`)**：单次调用并行提取短期历史、长期事实、任务 DAG 状态与情境事件。
- **跨层增量归档 (`recordTurn`)**：非阻塞将最新对话回合同步分发更新至 Short, Long, Task, Episodic 四个记忆存储。

### 4.3 统一 RAG 知识库门面 (`KnowledgeEngine`)

- **多租户混合检索 (`search`)**：向量余弦相似度 + Portable BM25 + Reciprocal Rank Fusion (RRF k=60) 重排，并实施 `hybridScore >= 0.40` 熔断拦截。
- **原子级文件热替换 (`replaceFile`)**：按 `sourceUrl` 物理清扫废弃切片，并在单次 Pass 中重新切片、提炼 Anthropic Contextual Summary 与写入向量。

### 4.4 领域服务与 API 控制器解耦 (`ChatSessionService` & `ApprovalService`)

- 将原本充斥在 Route Handler 中的配额防护、Singleflight 去重、人工客服会话拦截、分布式锁与 Agent 恢复逻辑提炼为 `ChatSessionService` 与 `ApprovalService`，实现标准“瘦 Controller + 胖 Service”架构。

### 4.5 工作流调度与本地模拟器统一 (`WorkflowOrchestrator`)

- **`WorkflowOrchestrator.dispatchJob(opts)`**：自动探测 Temporal 物理服务可用性，并在离线或测试环境下无缝降级到 LangGraph 直跑模式，同时自动绑定 Serverless `waitUntil` 容器解冻声明。

### 4.6 实时 SSE 长连接客户端 (`AgentStreamClient`)

- 封装标准的 `AgentStreamClient` 订阅客户端，向 UI 暴露 `onStatus`, `onResult`, `onError` 强类型回调，使网络传输彻底脱离 React Component 渲染树。

### 4.7 金融级人机协同与认知回溯决策环 (HITL)

- 支持无状态挂起、大脑打倒挡回溯、超时解挂熔断与用户主动取消机制，实现多请求状态的物理隔离。

### 4.8 SaaS 级多租户隔离与 Contextual RAG 检索

- Drizzle ORM 查询强行挂载 `WHERE business_id = :tenantId` 条件子句，从数据源头封杀越权风险。

### 4.9 物理工具链政策红线守卫 (SOP Guardrail)

- 物理工具链底层硬编码商户退货窗口（Nike 30天 / Adidas 14天），超期订单在工具内部物理抛出异常。

### 4.10 双通道并发防刷与 Redis SETNX 分布式锁

- Singleflight 请求合并 + Redis `SETNX` 分布式并发锁，配有 5s 自动过期与内存 `localLocks` 降级锁保护。

### 4.11 SaaS 算力审计与财务账单度量系统

- 决策结束后异步冲刷 `session_metrics` 账单，提供高精度算力开销与 Autopilot 自动放行率统计。

---

## 5. 质量保障与评测体系 (Testing & Tooling)

- **全量单元测试与集成测试 (Bun Test)**：
  包含了针对 `StepExecutionEngine`, `ApprovalPolicyEngine`, `KnowledgeEngine`, `AgentMemoryEngine`, `WorkflowOrchestrator`, `ChatSessionService`, `ApprovalService` 的专属单元测试，覆盖 46+ 个关键验证点（100% 绿色通过）。
- **Biome (Rust-powered Linter/Formatter)**：
  高速代码格式化与依赖排序，保障 CI/CD 规范。
- **Playwright (E2E 测试)**：
  自动化验证多轮对话、工单核签面板与状态持久化。
- **Promptfoo (Prompt 评测)**：
  评测提示词防越狱、大意图识别准确率与回复质量。

---

## 6. 开发与部署命令

### 6.1 运行全量单元测试与代码校验

```bash
# 运行全量 46+ 单元与集成测试
bun test

# 运行 Biome 格式化与 Linter 检查
bun run lint
```

### 6.2 启动本地开发服务

```bash
# 启动全部服务 (Next.js 核心控制台 + Admin 管理端)
bun run dev
```

访问 [http://localhost:3000](http://localhost:3000) 即可开启体验！

---

## 7. 生产上线前 SOP 流程 (Pre-Launch Checklist & Standard Operating Procedure)

在将 **smartServe-agent** 智能客服决策中台平台正式部署至生产环境（Production）前，必须按照以下标准 SOP 步骤逐一核验与执行，以确保高可用性、金融级安全性与算力成本可控：

```
┌────────────────────────────────────────────────────────────────────────┐
│                        生产环境上线 SOP 标准流程                         │
│                                                                        │
│  [1. 基础设施与环境] ──► [2. 安全防护与脱敏] ──► [3. 全套自动化回归测试] │
│                                                                  │     │
│  [6. 可观测性与告警] ◄── [5. 熔断与防暴刷验证] ◄── [4. 高并发性能压测]   │
└────────────────────────────────────────────────────────────────────────┘
```

### 7.1 基础设施与环境验证 (Environment & Infrastructure Setup)

1. **数据库准备 (PostgreSQL & pgvector)**：
   - 生产级 PostgreSQL 数据库（建议 15+）且必须安装 `pgvector` 向量扩展插件。
   - 执行数据库 Migration 物理生成表结构：
     ```bash
     bun drizzle-kit generate
     bun drizzle-kit push
     ```
   - 执行种子数据初始化与租户策略灌入：
     ```bash
     bun packages/db/src/seed.ts
     ```
2. **Redis 物理集群验证 (Redis Distributed Cache & Locks)**：
   - 确认 Redis 连接地址、端口及鉴权密码配置（如 `REDIS_URL=redis://:password@redis-host:6379`）。
   - 验证 Redis `SETNX` 分布式锁与缓存可用性（确保工单核准防重入与并发请求 Singleflight 能正常工作）。
3. **Temporal 分布式工作流服务 (Temporal Engine)**：
   - 部署 Temporal 生产级 Server（端口 `7239`），并启动 Temporal Worker 进程守护：
     ```bash
     bun --filter engine worker
     ```

### 7.2 安全防护与密钥脱敏 Check (Security & Secrets Management)

1. **环境变量脱敏**：
   - 检查生产环境 `.env` 文件，确保包含：`OPENAI_API_KEY` / `GEMINI_API_KEY`、`POSTGRES_URL`、`REDIS_URL`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY` 等。
   - **绝对禁止**将密钥、数据库密码或凭证直接硬编码写入 git 仓库提交。
2. **SaaS 多租户物理隔离校验**：
   - 确认 Drizzle ORM 查询物理附加了 `business_id` 条件隔离，防止跨商户数据透传与越权。
3. **退款政策红线与金融印鉴校验 (Financial SOP & Audit Trail)**：
   - 确认工具层 `processRefund` 绑定的商户时效限制（Nike 30天 / Adidas 14天 / Ecommerce 7天）与 SHA256 哈希印鉴签名已开启。

### 7.3 质量验证与自动化测试全覆盖 (Automated Testing & Quality Gate)

上线前必须通过 100% 的自动化测试流水线：

```bash
# 1. 运行全套单元测试与集成测试 (包含 CircuitBreaker、QuotaGuard、Planner、Executor、Memory 46+ 测试点)
bun test

# 2. 运行 Playwright 端到端浏览器对话测试
bun run test:e2e

# 3. 运行 Promptfoo 大模型提示词防越狱与意图准确率评测
bun run test:prompt

# 4. 运行 Biome 极速代码规范校验
bun run lint
```

### 7.4 高并发性能压测 (High-Concurrency Load Testing)

上线前使用内置的压测脚本测试系统吞吐量与延迟表现：

```bash
# 启动 20 并发线程、总计 100 笔请求的 SSE 吞吐量压测
bun run test:load --concurrency 20 --total 100 --url https://your-production-domain.com
```

- **验证指标**：
  - TTFB (首字节响应延迟) ≤ 300ms
  - 成功率 (Success Rate) = 100%
  - P90 延迟 ≤ 1500ms (基于 Fast-Path 旁路优化)

### 7.5 熔断与配额防暴刷机制验证 (Circuit Breaker & Quota Guard)

1. **租户级 QuotaGuard 配额保护**：
   - 单用户/租户接口频率上限：**60 次/分钟**
   - 算力 Token 每日上限：**500,000 Tokens/天**
   - 超出限制时系统自动触发 `429 Too Many Requests`，保护系统不被恶意流量暴刷。
2. **LLM 断路器熔断降级 (CircuitBreaker)**：
   - 当上游大模型遭遇连续 5 次报错（如 5xx 或 429 速率限制）时，自动触发熔断状态（30 秒冷却）。
   - 熔断期间系统自动降级，向用户推送友好自愈提示，防止集群因请求积压崩溃。

### 7.6 可观测性与健康检查 (Observability & Health Checks)

1. **APM 算力大盘与 Trace 跟踪**：
   - 登录 Langsmith / Langfuse 控制台，确认所有 Agent 节点决策流、大模型输入输出及工具调用均可实时生成 Trace。
   - 访问前端 `/api/analytics` 查看 SaaS BI 财务大盘数据。
2. **健康检查轮询**：
   - 配置 LB / K8s 存活探针轮询 `GET /api/health` 端口，实时监控系统健康状态。

---

_本文档基于 smartServe-agent 物理落地的代码结构进行详尽整理与更新。_
