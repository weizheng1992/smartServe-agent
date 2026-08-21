# 🚀 smartServe-agent: 分布式多租户 SaaS 智能客服决策中台平台

smartServe-agent 是一款基于 **Turborepo Monorepo**、**Bun 运行环境** 与 **LangGraph 决策图** 构建的日活千万级、高弹性、高防卫金融级智能客服 Agent 决策平台。

系统原生支持 **SaaS 多租户物理隔离**、**人工核签红线拦截与重规划自适应回溯**、**Anthropic Contextual RAG（上下文增益知识库检索）**，并配备了 **Redis 分布式并发锁**、**物理自愈指数退避 LLM HA-Proxy**、以及**高敏捷 SaaS 财务算力账单仪表盘**。

在近期，我们对整个系统进行了大规模的**多模态视觉感知与智能破损定责 (Multimodal Vision & Damage Assessment)**、**JSON Blocks 结构化富交互卡片中台 (`CardSynthesizer` & `RichCardRenderer`)**、**图片安全上传流水线** 以及 **纯血 PostgreSQL 架构升级（彻底移除内存模拟假库 FakePool，实现单一真实数据源）** 等核心能力加固。

---

## 目录

1. [项目架构与双模引擎设计](#1-项目架构与双模引擎设计)
2. [高精准工作空间目录树 (Workspace Tree)](#2-高精准工作空间目录树-workspace-tree)
3. [核心模块深度技术讲解 (Deep Module Breakdown)](#3-核心模块深度技术讲解-deep-module-breakdown)
   - [3.1 `apps/web` 前端可视化与 API 服务层](#31-appsweb-前端可视化与-api-服务层)
   - [3.2 `packages/engine` 核心 Agent 智能决策图与调度引擎](#32-packagesengine-核心-agent-智能决策图与调度引擎)
   - [3.3 `packages/db` 纯血 PostgreSQL 真实关系型数据接入与领域仓储](#33-packagesdb-纯血-postgresql-真实关系型数据接入与领域仓储)
   - [3.4 `packages/tools` 物理工具链、公共订单服务与 PII 安全脱敏](#34-packagestools-物理工具链公共订单服务与-pii-安全脱敏)
   - [3.5 `packages/observability` 算力计量与全链路 Trace 日志](#35-packagesobservability-算力计量与全链路-trace-日志)
   - [3.6 `packages/business-configs` 多商户 SaaS 动态策略配置](#36-packagesbusiness-configs-多商户-saas-动态策略配置)
   - [3.7 `packages/ui` 共享 UI 组件库与零依赖富卡片族](#37-packagesui-共享-ui-组件库与零依赖富卡片族)
4. [核心底层深度设计实现细节](#4-核心底层深度设计实现细节)
   - [4.1 任务并行执行与安控网关 (`StepExecutionEngine` & `ApprovalPolicyEngine`)](#41-任务并行执行与安控网关-stepexecutionengine--approvalpolicyengine)
   - [4.2 统一四层记忆高深度门面 (`AgentMemoryEngine`)](#42-统一四层记忆高深度门面-agentmemoryengine)
   - [4.3 统一 RAG 知识库门面 (`KnowledgeEngine`)](#43-统一-rag-知识库门面-knowledgeengine)
   - [4.4 领域服务与 API 控制器解耦 (`ChatSessionService` & `ApprovalService`)](#44-领域服务与-api-控制器解耦-chatsessionservice--approvalservice)
   - [4.5 工作流调度与本地模拟器统一 (`WorkflowOrchestrator`)](#45-工作流调度与本地模拟器统一-workfloworchestrator)
   - [4.6 实时 SSE 长连接客户端 (`AgentStreamClient`)](#46-实时-sse-长连接客户端-agentstreamclient)
   - [4.7 金融级人机协同与认知回溯决策环 (HITL)](#47-金融级人机协同与认知回溯决策环-hitl)
   - [4.8 SaaS 级多租户隔离与 Contextual RAG 检索](#48-saas-级多租户隔离与-contextual-rag-检索)
   - [4.9 物理工具链政策红线守卫与 PII 递归脱敏切面](#49-物理工具链政策红线守卫与-pii-递归脱敏切面)
   - [4.10 双通道并发防刷与 Redis SETNX 分布式锁](#410-双通道并发防刷与-redis-setnx-分布式锁)
   - [4.11 SaaS 算力审计与财务账单度量系统](#411-saas-算力审计与财务账单度量系统)
   - [4.12 纯血 PostgreSQL 单一真实数据源 (Single Source of Truth) 与 Zero IDOR 防护](#412-纯血-postgresql-单一真实数据源-single-source-of-truth-与-zero-idor-防护)
   - [4.13 多模态视觉感知、面单 OCR 与富交互卡片协议体系](#413-多模态视觉感知面单-ocr-与富交互卡片协议体系)
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
│     │                 ▲              │ (无依赖子任务)       │            │
│     │                 │              └─ 并行 Promise.all ─┘            │
│     │                 └───────────────── validator(校验) ◄┘            │
│     ▼                                                                  │
│   finish(终点合成回复，依据真实物理 RAG 和工具数据提炼答复)                  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        数据持久化与二级缓存层                         │
│  - 纯物理 PostgreSQL 数据库 (Drizzle ORM & 物理连接池 pg.Pool，单一真实数据源) │
│  - Redis 物理分布式缓存 (含 localLocks 内存降级锁保护与 DEL 缓存自洁)    │
│  - PII 参数脱敏中间件 (物理过滤身份证/电话/银行卡，合规落盘日志)         │
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
│   │   │   │   │   ├── messages/    # 会话历史消息同步接口
│   │   │   │   │   ├── preferences/ # 用户画像偏好检索接口
│   │   │   │   │   ├── threads/     # 会话管理 (增删查) 接口
│   │   │   │   │   ├── upload/      # 多模态图片安全上传端点 (10MB 限制 & MIME 白名单)
│   │   │   │   │   ├── services/    # ChatSessionService & ApprovalService 领域服务层
│   │   │   │   │   ├── quotaGuard.ts# 租户级请求频次与 Token 配额守卫
│   │   │   │   │   └── route.ts     # 接收对话请求分发中转控制器
│   │   │   │   ├── chat/[jobId]/stream/ # SSE 实时状态机节点日志广播管道
│   │   │   │   ├── health/          # 系统健康检查轮询探针
│   │   │   │   └── tenant/          # SaaS 商户自主入驻与配置中心 API
│   │   │   │       ├── onboard/     # 商户自主注册与默认配置初始化
│   │   │   │       ├── config/      # 品牌提示词/参数 Draft与Publish版本管理
│   │   │   │       ├── tools/       # OpenAPI 动态工具注册与凭证加密
│   │   │   │       └── knowledge/upload/ # 多格式文档切片与 Contextual RAG 批量摄入
│   │   │   ├── home/                # 核心控制台面板
│   │   │   │   ├── components/      # 模块化 UI 组件
│   │   │   │   │   ├── audit/       # HITL 审核工作台子组件 (AuditDesk, ApprovalDetailView, ApprovalList)
│   │   │   │   │   ├── APMPanel.tsx # 性能监控、Token 成本与 TTFT 仪表盘
│   │   │   │   │   ├── ChatArea.tsx # 主对话区域、多模态图片上传/预览条与卡片交互
│   │   │   │   │   └── LeftSidebar.tsx # 会话历史列表、商户切换与退出登录
│   │   │   │   ├── hooks/           # useChatMessages (基于 AgentStreamClient), useChatThreads, useApprovals
│   │   │   │   └── utils/           # AgentStreamClient (SSE 订阅客户端) & translateTaskPlan (任务英转中翻译)
│   │   │   ├── login/               # 商户登录界面 (支持租户切换与会话自愈)
│   │   │   └── page.tsx             # 客服核心交互大屏入口
│   │   ├── components/              # 登录与通用组件
│   │   ├── e2e/                     # Playwright 端到端 UI 自动化测试
│   │   └── package.json
│   │
│   └── admin/                       # 商户/系统级人工核签中台大屏 (3001 端口)
│       ├── app/                     # App Router 路由结构
│       │   └── home/                # 工单流转与人工接管控制台
│       │       ├── components/      # 人工接管与工单审核模块
│       │       │   ├── chat/        # 实时人工客服聊天子组件 (ChatMessageFeed, HumanChatFooter)
│       │       │   ├── Header.tsx   # 中台顶部导航与系统指标概览
│       │       │   ├── HistoricalAudits.tsx # 历史审批归档与审计追踪
│       │       │   ├── HumanChatModal.tsx   # 人工客服主动接管实时 IM 抽屉
│       │       │   ├── Metrics.tsx  # 财务度量、放行率与 SLA 报表
│       │       │   ├── PendingApprovals.tsx # 待审核工单流转列表
│       │       │   └── PersonaAudit.tsx     # 用户长期偏好画像审计看板
│       │       └── hooks/           # useAdminStore & types
│       └── package.json
│
├── packages/
│   ├── engine/                      # 核心 Agent 决策图与分布式工作流 (LangGraph + Temporal)
│   │   ├── src/
│   │   │   ├── graph/               # 决策图定义与节点
│   │   │   │   ├── nodes/           # 深度领域决策节点
│   │   │   │   │   ├── triage/      # 3 级意图分流引擎 (规则旁路 + 语义嵌入相似度 + LLM 槽位提取)
│   │   │   │   │   ├── approvalPolicyEngine.ts # 金融安全红线与审批策略评估网关
│   │   │   │   │   ├── stepExecutionEngine.ts  # 任务执行引擎与 Promise.all 无依赖子任务并行调度器
│   │   │   │   │   ├── executorFastPath.ts     # 高频无状态工具极速执行旁路
│   │   │   │   │   ├── executorApprovals.ts    # HITL 人工工单落盘与状态流转
│   │   │   │   │   ├── planner.node.ts         # 动态规划节点 (DAG 子任务依赖构建与多意图生成)
│   │   │   │   │   ├── validator.node.ts       # 步骤结果后置反思与决策校验
│   │   │   │   │   └── finish.node.ts          # 终点回复合成与真实 RAG/工具数据提炼
│   │   │   │   ├── eventEmitter.ts  # 本地直跑事件广播器 (Node.js EventEmitter)
│   │   │   │   └── buildGraph.ts    # 编译 LangGraph 并集成死循环物理熔断器
│   │   │   ├── vision/              # 多模态视觉感知与智能破损定责服务 (VisionAnalyzerService)
│   │   │   ├── cards/               # 统一结构化卡片合成引擎 (CardSynthesizer)
│   │   │   ├── memory/              # AgentMemoryEngine 统一 4 重多维度状态记忆门面
│   │   │   │   ├── agentMemoryEngine.ts # 统一 4 层记忆并行拉取与归档门面
│   │   │   │   ├── shortMemory.ts   # 短期对话历史记忆
│   │   │   │   ├── longMemory.ts    # 长期事实卡片提取与向量记忆
│   │   │   │   ├── episodicMemory.ts# 真实情境回忆事件记忆
│   │   │   │   └── taskMemory.ts    # 物理 Task Plan 状态持久化层
│   │   │   ├── rag/                 # KnowledgeEngine 统一 RAG 知识库门面
│   │   │   │   ├── knowledgeEngine.ts # 混合检索、文件热替换、单切片维护与目录入库门面
│   │   │   │   ├── contextualRag.ts # Anthropic Contextual RAG 混合检索引擎 (BM25 + 向量 + RRF)
│   │   │   │   ├── documentIngestionService.ts # 多格式文档解析、递归边界切片与情境摘要提取服务
│   │   │   │   ├── chunker.ts       # Markdown 智能分块切片算法
│   │   │   │   ├── contextGenerator.ts # 上下文总结摘要增强生成器
│   │   │   │   └── ingestTxtFiles.ts# 物理文档自动解析与批量注入器
│   │   │   ├── orchestrator/        # WorkflowOrchestrator 统一工作流调度与降级防御层
│   │   │   │   └── workflowOrchestrator.ts # 统一 Temporal 工作流与本地 LangGraph 调度
│   │   │   ├── llm/                 # LLM 自愈重试与 CircuitBreaker 断路器
│   │   │   └── temporal/            # 分布式工作流编排 (client, worker, workflows, activities)
│   │   └── tests/                   # 86+ 全量单元与集成测试套件
│   │
│   ├── db/                          # 纯物理关系型数据库层 (Drizzle ORM & PostgreSQL 连接池)
│   │   ├── drizzle/                 # 数据库 Migration 自动生成 SQL
│   │   └── src/
│   │       ├── repositories/        # 强类型领域仓储接口 (IUserRepository, IThreadRepository, IMessageRepository, IOrderRepository)
│   │       ├── services/            # 领域服务 (tenantService: 租户 IAM、成员角色、版本化配置与动态工具)
│   │       ├── client.ts            # 纯物理真实 PostgreSQL 数据库连接池 (pg.Pool) 与 Drizzle 实例 (单一真实数据源)
│   │       ├── schema.ts            # 3NF 物理表结构定义 (tenants, tenant_members, tenant_configs, tenant_tools, orders, messages 等)
│   │       ├── scripts/             # 数据库诊断与知识库导入运维脚本
│   │       └── seed.ts              # 物理种子数据与多商户策略注入脚本
│   │
│   ├── tools/                       # 物理工具链、公共领域服务与 PII 安全脱敏
│   │   ├── src/
│   │   │   ├── orderDomainService.ts# 订单领域服务 (含 createOrder, listUserOrders, processRefund, changeShippingAddress)
│   │   │   ├── ecommerce.tools.ts   # 电商标准 Tool 注册定义 (getOrderStatus, processRefund, listUserOrders, createOrder 等)
│   │   │   ├── openapi/             # OpenAPI 3.0 动态工具工厂 (dynamicToolFactory) 与 SSRF 运行时安全沙箱 (ssrfGuard)
│   │   │   ├── crypto/              # 商户 API 凭证安全中心 (secrets: 基于 HKDF 租户派生密钥的 AES-256-GCM 加密与脱敏)
│   │   │   ├── scrubber.ts          # PII 敏感数据递归脱敏切面 (掩码手机/身份证/银行卡/邮箱)
│   │   │   ├── screenshot.tools.ts  # Puppeteer 高清网页物理截图工具 (静态文件保存与安全返回)
│   │   │   ├── cache.ts             # Redis + 本地 Map 双模二级缓存层 (带自动失效与 TTL)
│   │   │   └── registry.ts          # 统一 Tool 注册表 (透明注入 PII 脱敏中间件)
│   │   └── tests/                   # 订单领域服务、加密中心、动态工具与 PII 脱敏集成测试
│   │
│   ├── observability/               # 财务度量分析与 APM Trace 观测包 (Langfuse, Pino Logger, metrics)
│   ├── business-configs/            # SaaS 多商户动态 JSON 策略配置 (ecommerce.config.ts)
│   ├── types/                       # 全局强类型定义共享包 (card, agent, approval, config, db, event, observability, tool)
│   └── ui/                          # 共享 UI 组件库、原生 SVG 图标与富交互卡片族 (OrderCard, TrackingTimeline, RefundConfirmationCard, DamageAssessmentCard, QuickReplies)
│
├── CONTEXT.md                       # 领域上下文与深度模块规范名词表
├── CLAUDE.md                        # Claude Code 开发 SOP 指南
├── CHANGELOG.md                     # 全版本里程碑演进记录
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
  - `StepExecutionEngine`: 封装快速通道匹配、参数提取、策略评估与工具派发，集成基于 `Promise.all` 的无依赖子任务并行执行器；
  - `ApprovalPolicyEngine`: 封装双重退款拦截、免签额度评估、高价值地址变更校验与超时解挂；
  - `AgentMemoryEngine`: 统一调度短期、长期、任务与情境四层记忆；
  - `KnowledgeEngine`: 提供 SaaS 隔离混合检索、原子级文件热替换与目录入库；
  - `WorkflowOrchestrator`: 统一调度 Temporal 生产工作流与本地 LangGraph 模拟器。

### 3.3 `packages/db` 纯血 PostgreSQL 真实关系型数据接入与领域仓储

- **职责范围**: 关系型数据物理持久化与事务隔离，提供单一真实数据源（Single Source of Truth）。
- **核心模块**:
  - `client.ts`: 纯物理 PostgreSQL 连接池 (`pg.Pool`) 与 Drizzle ORM 单例，彻底移除了 `FakePool` 与内存模拟分支，保证外部 SQL 插入与系统实时查询 100% 同步；
  - `packages/db/src/repositories/`: 提供强类型领域仓储接口（`IUserRepository`, `IThreadRepository`, `IMessageRepository`, `IOrderRepository`），实现清晰的领域层解耦；
  - `schema.ts`: 规范 3NF 关系型表结构，支持物理外键级联与 SaaS 租户字段隔离。

### 3.4 `packages/tools` 物理工具链、公共订单服务与 PII 安全脱敏

- **职责范围**: 真实物理工具执行层、业务领域服务与数据安全合规切面。
- **核心模块**:
  - `orderDomainService.ts`: 提供包含 `createOrder`（标准下单）、`listUserOrders`（零越权查单）、`processRefund`（防重退款）与 `changeShippingAddress`（高价值地址审批门禁）在内的统一领域服务；
  - `scrubber.ts`: 递归 PII 脱敏中间件，自动对手机号、身份证、银行卡及邮箱进行掩码处理；
  - `screenshot.tools.ts`: 本地物理 Chrome/Chromium 浏览器高清抓图与静态文件落盘；
  - `cache.ts`: Redis 物理集群直连与本地内存双模二级缓存。

### 3.5 `packages/observability` 算力计量与全链路 Trace 日志

- **职责范围**: 全链路 APM 性能度量、LLM Token 计费审计与 Pino 结构化日志追踪。

### 3.6 `packages/business-configs` 多商户 SaaS 动态策略配置

- **职责范围**: 维护不同商户（如 Nike、Adidas、主站电商）的退款免签阈值、退货政策时效与自定义提示词快照。

### 3.7 `packages/ui` 共享 UI 组件库与零依赖富卡片族

- **职责范围**: 提供跨 Web 与 Admin 端的高保真设计语言、原生 SVG 可缩放矢量图标库与 JSON Blocks 富交互卡片组件族（`OrderCard`、`TrackingTimeline`、`RefundConfirmationCard`、`DamageAssessmentCard`、`QuickReplies` 与 `RichCardRenderer`）。

---

## 4. 核心底层深度设计实现细节

### 4.1 任务并行执行与安控网关 (`StepExecutionEngine` & `ApprovalPolicyEngine`)

- **`StepExecutionEngine` 与并行执行器 (Parallel Subtask Executor)**：
  - 将单体执行节点拆解为高深度门面，屏蔽参数匹配与工具调度细节；
  - 内置 **DAG 并行执行器**：自动扫描当前步骤之后连续且无依赖的 Fast-Path 独立子任务（如“查单状态”与“查历史订单”同时发起），通过 `Promise.all` 实行并发极速调起，多任务执行延迟降低 50% 以上。
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

### 4.9 物理工具链政策红线守卫与 PII 递归脱敏切面

- **业务 SOP 红线**：物理工具链底层硬编码商户退货窗口（Nike 30天 / Adidas 14天），超期订单在工具内部物理抛出异常；
- **PII 递归数据脱敏**：所有注册到 `registry.ts` 的工具在执行前与返回后均自动流经 `scrubPii()` 中间件，自动掩码敏感字段，杜绝泄露到日志与遥测系统。

### 4.10 双通道并发防刷与 Redis SETNX 分布式锁

- Singleflight 请求合并 + Redis `SETNX` 分布式并发锁，配有 5s 自动过期与内存 `localLocks` 降级锁保护。

### 4.11 SaaS 算力审计与财务账单度量系统

- 决策结束后异步冲刷 `session_metrics` 账单，提供高精度算力开销与 Autopilot 自动放行率统计。

### 4.12 纯血 PostgreSQL 单一真实数据源 (Single Source of Truth) 与 Zero IDOR 防护

- 彻底移除任何脱机内存假库，无论是外部 SQL 手工注入还是前端 API 创建订单，数据统一物理落盘在同一个 PostgreSQL 实例；
- 工具层查询物理结合会话 `threadId` 反查用户身份，严格执行 `WHERE user_id = :userId AND business_id = :businessId`，彻底防范越权串单。

### 4.13 多模态视觉感知、面单 OCR 与富交互卡片协议体系

- **Triage 视觉感知与 1500ms 超时熔断**：用户上传图片时优先于文本通过 `VisionAnalyzerService` 进行图文多模态分析，提取面单订单号（`ORD-XXXXX`）与快递单号（`SFXXXXXXXX`）并自动注入意图分类；内置 1500ms 竞争超时，网络波动时秒级降级至本地规则提取。
- **商品破损瑕疵三级智能定损**：支持 `negligible`（完好）、`minor`（轻微瑕疵/外包装损）、`severe`（严重破损）定责评级，自动联动审批策略网关决策秒级赔付或人工复核。
- **PII 隐私脱敏切面**：视觉分析与 OCR 输出自动对手机号（`138****5678`）、身份证（`[ID_CARD_REDACTED]`）与银行卡（`[BANK_CARD_REDACTED]`）强制掩码。
- **JSON Blocks 结构化卡片协议**：标准化 `order_card`、`tracking_timeline`、`refund_confirmation`、`damage_assessment` 与 `quick_replies` 协议，并通过 SSE 随流式消息挂载返回。
- **零外部图标依赖 UI 渲染体系**：基于原生 SVG 矢量图标封装高保真组件，支持订单快速追踪、一键申请退款与快捷回复气泡联动。
- **安全图片上传流水线**：`/api/chat/upload` 接口校验 MIME Type（JPEG/PNG/WebP/GIF）与 10MB 物理上限，通过随机 UUID 物理落盘并派发安全访问 URL。

---

## 5. 质量保障与评测体系 (Testing & Tooling)

- **全量单元测试与集成测试 (Bun Test)**：
  包含针对 `OrderDomainService`、`StepExecutionEngine`（并行子任务执行）、`ApprovalPolicyEngine`、`KnowledgeEngine`、`AgentMemoryEngine`、`VisionAnalyzerService`（多模态感知与 OCR 实体提取）、`CardSynthesizer`（富交互卡片合成）、图片安全上传以及 PII 脱敏中间件的专属集成测试，覆盖 **86+ 个核心用例 (100% 绿色通过)**。
- **Biome (Rust-powered Linter/Formatter)**：
  高速代码格式化与依赖排序，保障 CI/CD 规范。
- **Playwright (E2E 测试)**：
  自动化验证多轮对话、工单核签面板与状态持久化。
- **Promptfoo (Prompt 评测)**：
  评测提示词防越狱、多意图识别准确率与回复质量。
- **高并发流式压测大盘 (`scripts/load-test.ts`)**：
  支持多用户多商户并发压力测试与首字生成延迟 (TTFT) 物理测速。

---

## 6. 本地开发与启动指南 (Local Quick Start)

### 6.1 环境与依赖准备

- **包管理器 / 运行时**：[Bun](https://bun.sh/) (>= 1.1.0)
- **容器环境**：Docker & Docker Compose（用于一键拉起 PostgreSQL、Redis、Temporal）

### 6.2 极速一键本地启动步骤

```bash
# 1. 复制环境变量配置文件
cp .env.example .env

# 2. 一键启动本地核心基础设施容器 (PostgreSQL 5432 & Redis 6379)
bun run docker:up

# 3. 推送数据库 Schema 并注入多租户种子数据
bun run db:push
bun run db:seed

# 4. 启动前端应用集群 (Next.js 用户前台 :3000 + Admin 审计管理后台 :3001)
bun run dev
```

> 💡 **关于 Temporal 工作流引擎**：
>
> - **默认模式**：未启动 Temporal 时，系统自动启用 **High-Fidelity LangGraph 仿真模式** 直跑（无需拉取 Temporal 镜像，开箱即用）。
> - **生产级工作流模式**：若需启用分布式 Temporal Server，可执行：
>   ```bash
>   bun run docker:temporal   # 启动 Temporal Server 容器 (:7239 与 Web UI :8233)
>   bun run worker            # 启动 Temporal Worker 进程
>   ```

---

### 6.3 常用开发命令速查

| 操作类别             | 命令                      | 说明                                                                   |
| :------------------- | :------------------------ | :--------------------------------------------------------------------- |
| **全量启动**         | `bun run dev`             | 并行启动 Next.js 前端 (`apps/web:3000`) 与管理后台 (`apps/admin:3001`) |
| **核心基础设施容器** | `bun run docker:up`       | 一键启动本地 PostgreSQL (5432) 与 Redis (6379) 容器                    |
| **Temporal 容器**    | `bun run docker:temporal` | 可选：启动 Temporal Dev Server 容器 (:7239 & Web UI :8233)             |
| **Temporal Worker**  | `bun run worker`          | 可选：启动 `packages/engine` 的 Temporal 物理工作流 Worker 进程        |
| **容器停止**         | `bun run docker:down`     | 停止并释放本地 Docker 容器资源                                         |
| **数据库同步**       | `bun run db:push`         | 基于 Drizzle ORM 同步 Schema 结构至真实 PostgreSQL                     |
| **数据种子灌入**     | `bun run db:seed`         | 初始化租户策略、商品与模拟订单基础数据                                 |
| **单元与集成测试**   | `bun test`                | 运行全部 86+ 单元测试与集成测试用例 (100% 通过)                        |
| **代码规范与格式化** | `bun run lint`            | 运行 Biome 极速代码检查与格式化                                        |
| **端到端测试**       | `bun run test:e2e`        | 运行 Playwright 浏览器自动化交互测试                                   |
| **提示词与意图评测** | `bun run test:prompt`     | 运行 Promptfoo 评测提示词与意图分流准确率                              |
| **并发压测大盘**     | `bun run test:load`       | 压测 SSE 流式接口吞吐量与 TTFT 延迟                                    |

---

### 6.4 本地默认服务端口表

| 服务名称                          | 端口   | 访问地址 / 连接说明                                                  |
| :-------------------------------- | :----- | :------------------------------------------------------------------- |
| **Web 智能客服对话前端**          | `3000` | [http://localhost:3000](http://localhost:3000)                       |
| **Admin 人工核签与审计中台**      | `3001` | [http://localhost:3001](http://localhost:3001)                       |
| **Temporal Web UI 管理控制台**    | `8233` | [http://localhost:8233](http://localhost:8233)                       |
| **PostgreSQL 关系型数据库**       | `5432` | `postgres://agent_user:agent_password@localhost:5432/agent_platform` |
| **Redis 分布式缓存与分布式锁**    | `6379` | `redis://:redis_password@127.0.0.1:6379`                             |
| **Temporal gRPC Server 服务端口** | `7239` | `127.0.0.1:7239`                                                     |

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
# 1. 运行全套单元测试与集成测试 (包含 CircuitBreaker、QuotaGuard、Planner、Executor、Memory 56+ 测试点)
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
