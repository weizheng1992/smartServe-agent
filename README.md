# 🚀 smartServe-agent: 分布式多租户 SaaS 智能客服与控制平面中台 (v2 Architecture)

smartServe-agent 是一款基于 **Turborepo Monorepo**、**Bun 运行环境**、**NestJS 高性能网关** 与 **LangGraph 决策图** 构建的生产级、高弹性、金融安全级智能客服与多租户管理中台平台。

> 💡 **版本与架构演进说明**：
>
> - **v2 (当前分支 / feat/open-integration-skills-mcp)**：完成了从全单体 Next.js 到现代化分层中台的**彻底重构**。包含高内聚现代化 SaaS 控制平面（`apps/admin`）、全功能 NestJS 微服务网关（`apps/server`）、极速响应轻量客户端（`apps/web`）、参数化 SQL 沙箱、双层画像隔离与 Transactional Outbox 事务可靠机制。
> - **v1 (分支 `v1-main`)**：为初代单体 Next.js 15 App Router 实现（包含早期的单页暗色客服与简单审批流）。

---

## 🌟 v2 核心重构与升级特性亮点 (Refactor Highlights)

| 核心维度                                 | ❌ v1-main (旧版本)                                    | ✨ v2 当前版本 (Enterprise SaaS Control Plane)                                                                                                                                                     |
| :--------------------------------------- | :----------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **中台控制平面 (`apps/admin`)**          | 单页暗色堆叠界面、模板代码冗余、缺乏模块化与通用 CRUD  | **全新现代简约 SaaS 中台**：10 大独立路由子模块，封装高复用 CRUD UI 套件 (`DataTable`, `FilterBar`, `DetailDrawer`, `FormModal`, `ConfirmDialog`) 与 `useAdminCrud` 状态流，集成全局租户实时穿透。 |
| **服务端网关 (`apps/server`)**           | Next.js API Routes 充当轻量接口，领域服务与控制器耦合  | **NestJS 工业级微服务网关**：模块化 Controller/Service 架构，内置开放商户 SPI 协议、全局异常过滤器、生命周期守护与强类型 DTO 校验。                                                                |
| **前端架构 (`apps/web` & `apps/admin`)** | Next.js 15 SSR/Node 运行时绑定                         | **Vite 6 + React 19 纯 SPA 高性能架构**：秒级冷启动、零死锁构建、首屏资源体积大幅降低。                                                                                                            |
| **审批事务与可靠性**                     | 内存与直接异步调度，存在幽灵工单 (Ghost Approval) 隐患 | **Transactional Outbox 事务一致性**：审批流状态变更与 Outbox 事件原子写入，配合后台异步对账与确定性幂等调度恢复机制。                                                                              |
| **客户画像与记忆系统**                   | 扁平用户偏好，缺乏租户边界，存在跨品牌数据泄露 (IDOR)  | **双层画像物理隔离体系 (`Dual-Tier Persona`)**：生理基础属性（如鞋码/过敏源）归属 `global` 全局共享；品牌消费习惯/特权优惠严格隔离至 `tenant` 租户级别。                                           |
| **BI 与 Text-to-SQL 安全**               | 字符串拼接 SQL 模板，存在注入风险与超时卡顿            | **参数化 AST 编译器与只读事务沙箱**：强制参数化占位符 (`$1`, `$2`) 绑定，`SET TRANSACTION READ ONLY` + 3000ms 强制超时熔断守护。                                                                   |
| **商户开放集成与技能生态**               | 静态内置工具与预设店铺规则                             | **开放商户 SPI 对接标准 & SOP 技能体系**：支持商户通过 Webhook/SPI 接入私有订单/物流系统，AES-256-GCM + HKDF 密钥派生，标准 RESTful `/api/skills/config` 动态重载与 MCP 复合生态。                 |
| **实时协同与流式推流弹性**               | 简单的 SSE 传输，断线重连丢失事件，缺乏坐席接管机制    | **双向实时接管网关与 Last-Event-ID 弹性回放**：基于 Socket.io + Redis Pub/Sub 实现毫秒级人工客服协同接管，`ChatService` 具备跨连接 Job 级事件缓存与断线增量重放。                                  |
| **质量保障与自动化测试**                 | 少量零散单元测试                                       | **全自动化测试流水线**：单测、集成测试、Playwright 真实浏览器 E2E 自动化测试全覆盖，Monorepo 一键验证。                                                                                            |

---

## 目录

1. [项目架构与服务拓扑](#1-项目架构与服务拓扑)
2. [Monorepo 工作空间与目录结构](#2-monorepo-工作空间与目录结构)
3. [10 大企业级管理模块 (apps/admin 控制平面)](#3-10-大企业级管理模块-appsadmin-控制平面)
4. [核心基础设施与安全底座 (Core Infrastructure)](#4-核心基础设施与安全底座-core-infrastructure)
   - [4.1 任务执行图与人机协同审批 (LangGraph + HITL)](#41-任务执行图与人机协同审批-langgraph--hitl)
   - [4.2 事务型发件箱与幂等重试 (Transactional Outbox)](#42-事务型发件箱与幂等重试-transactional-outbox)
   - [4.3 双层用户画像与多租户上下文装配 (Dual-Tier Persona)](#43-双层用户画像与多租户上下文装配-dual-tier-persona)
   - [4.4 参数化 SQL 编译与只读沙箱 (Parameterized SQL Sandbox)](#44-参数化-sql-编译与只读沙箱-parameterized-sql-sandbox)
   - [4.5 上下文增益 RAG 检索 (Contextual RAG)](#45-上下文增益-rag-检索-contextual-rag)
   - [4.6 开放商户 SPI 与动态工具市场 (Open Integration)](#46-开放商户-spi-与动态工具市场-open-integration)
   - [4.7 Agent SOP 技能与 MCP 复合能力生态 (Composite Skills & MCP)](#47-agent-sop-技能与-mcp-复合能力生态-composite-skills--mcp)
   - [4.8 Agent Harness 运行底座与四层记忆体系 (Quad-Memory Hierarchy)](#48-agent-harness-运行底座与四层记忆体系-quad-memory-hierarchy)
   - [4.9 生产级大模型综合安全风险评估与纵深防御 (Security & Guardrails)](#49-生产级大模型综合安全风险评估与纵深防御-security--guardrails)
   - [4.10 领域专职子智能体与隔离状态总线 (Multi-Agent Sub-Agents & State Bus)](#410-领域专职子智能体与隔离状态总线-multi-agent-sub-agents--state-bus)
   - [4.11 多租户 SQL 物理层下推隔离与越权防御 (SQL Push-Down Tenant Isolation)](#411-多租户-sql-物理层下推隔离与越权防御-sql-push-down-tenant-isolation)
   - [4.12 实时协同接管与 SSE 流式弹性回放 (Live Desk Takeover & SSE Resiliency)](#412-实时协同接管与-sse-流式弹性回放-live-desk-takeover--sse-resiliency)
5. [质量保障与全自动化测试 (Quality & Automation)](#5-质量保障与全自动化测试-quality--automation)
6. [开发与部署命令 (Quick Start)](#6-开发与部署命令-quick-start)

---

## 1. 项目架构与服务拓扑

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   前端接入层 (Frontend)                                  │
│   [apps/web (Port: 3000)]                                 [apps/admin (Port: 3001)]    │
│   用户多模态客服会话 / 富卡片 / 实时 SSE 流订阅              SaaS 现代化中台控制平面 (10 大模块)│
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │ HTTP / SSE / WebSocket 代理
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              NestJS 网关与后端控制层 (apps/server)                       │
│  - 统一 API 网关 / REST 控制器 / Auth 鉴权                                              │
│  - 开放商户 SPI 控制器 (/spi/v1/orders, /spi/v1/products, /spi/v1/user)                  │
│  - SSE 流式状态分发广播 / WebSocket 实时人工坐席协同通道                                  │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │ 领域调度
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              核心决策引擎 (packages/engine)                             │
│   triage(意图分流) ──→ planner(动态规划) ──→ merge ──→ loop [executor ⇄ validator]      │
│      │                                                     │                           │
│      └────────────── 极速问候旁路 / 语义缓存 ───────────────┴──→ finish(多模态输出合成) │
│  - ApprovalGatekeeper (安全风控核签)        - Transactional Outbox Worker (异步对账)   │
│  - ContextAssemblyPipeline (双层画像装配)   - MetricSemanticResolver (Text-to-SQL)      │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │
                        ┌──────────────────┴──────────────────┐
                        ▼                                     ▼
┌──────────────────────────────────────────┐  ┌──────────────────────────────────────────┐
│          物理持久层 (packages/db)         │  │          工具与通信 (packages/tools)     │
│  - 纯血 PostgreSQL (Drizzle ORM)         │  │  - 商户 SPI 物理连接器 (MerchantSpi)     │
│  - Redis 分布式锁 / SETNX 防并发 / 缓存   │  │  - OpenAPI 3.0 动态工具工厂 + SSRF 沙箱  │
│  - 只读分析沙箱 (3s 超时 / 参数化防注入) │  │  - PII 递归隐私脱敏 / 智能截图与 OCR     │
└──────────────────────────────────────────┘  └──────────────────────────────────────────┘
```

---

## 2. Monorepo 工作空间与目录结构

```text
.
├── apps/
│   ├── admin/                      # 现代化 SaaS 控制平面管理后台 (Vite 6 + React 19 + Tailwind CSS)
│   │   ├── src/
│   │   │   ├── components/crud/    # 统一封装的通用 CRUD 组件库 (DataTable, FilterBar, DetailDrawer, FormModal, ConfirmDialog)
│   │   │   ├── components/layout/  # 中台布局骨架 (AdminLayout, Sidebar, Header)
│   │   │   ├── hooks/              # 通用 CRUD 状态管理 Hook (useAdminCrud)
│   │   │   ├── store/              # 全局多租户状态中心 (tenantStore)
│   │   │   └── pages/              # 10 大 Feature 路由独立模块
│   │   │       ├── tenants/        # 1. 商户管理 (Tenant IAM, Webhook, 密钥配置)
│   │   │       ├── conversations/  # 2. 全景会话与决策回放 (全链路 Trace, 步骤透视)
│   │   │       ├── audits/         # 3. 风控审批审计 (HITL 核签, 驳回, 履约状态)
│   │   │       ├── personas/       # 4. 人物画像与记忆 (Global / Tenant 双层画像)
│   │   │       ├── rag-studio/     # 5. 知识库 RAG Studio (文档摄入, 演练台)
│   │   │       ├── skills-tools/   # 6. 技能与工具市场 (内置工具, 动态 OpenAPI, SPI)
│   │   │       ├── evals/          # 7. 评测实验 (准确率, 幻觉率, 安全红线)
│   │   │       ├── billing/        # 8. 计量计费 (Token 消耗, 成本折算, 配额管理)
│   │   │       ├── guardrails/     # 9. 安全合规围栏 (敏感词, 意图阻断, 正则拦截)
│   │   │       └── system-logs/    # 10. 系统与 LLM 日志 (耗时, Token, 报错追踪)
│   │   ├── tests/                  # 管理端集成测试套件
│   │   └── e2e/                    # Playwright 管理端端到端自动化测试
│   │
│   ├── server/                     # NestJS 工业级后端网关 (HTTP / SSE / WebSocket / SPI)
│   │   ├── src/modules/spi/        # 开放商户 SPI 标准实现与鉴权守卫
│   │   └── test/                   # NestJS E2E 与单元测试套件
│   │
│   ├── web/                        # 用户端客服对话系统 (Vite 6 + React 19 + SSE 长连接)
│   │   ├── src/components/         # 聊天区、富交互卡片、多模态上传
│   │   ├── src/hooks/              # 会话管理、流式接收、工单感知
│   │   └── tests/                  # 客户端对话场景与样式测试
│   │
│   └── merchant/                   # 独立电商示范商城 (Next.js 15)
│
├── packages/
│   ├── engine/                     # LangGraph 决策图、节点状态机、审批网关、双层画像装配
│   ├── db/                         # PostgreSQL 物理连接、Drizzle Schema、只读沙箱、Outbox 表
│   ├── tools/                      # 物理工具链、商户 SPI 客户端、SSRF 防御沙箱、PII 递归脱敏
│   ├── types/                      # 全仓共享 TypeScript 类型 (Cards, Agent, Config, Tools, Approval)
│   ├── ui/                         # 零外部依赖共享 UI 组件与原生矢量 SVG 图标库
│   ├── observability/              # Pino 日志记录与 Langfuse 链路追踪
│   └── business-configs/           # 多商户 SaaS 动态策略与退款限额配置
│
└── docs/                           # 深度技术架构规格书与设计指南
    ├── architecture/               # 核心架构指南 (architecture.md, contextual-rag.md, hitl-replanning.md 等)
    └── specs/                      # 生产级安全、弹性与商户入驻技术规格书
```

---

## 3. 10 大企业级管理模块 (`apps/admin` 控制平面)

全新重构的 `apps/admin` 控制平面为 SaaS 运营团队与商户管理员提供了全维度的管控能力：

1. **商户管理 (`/tenants`)**：管理多租户生命周期、套餐等级、退款风控阈值、SPI Webhook 回调地址与通信 API Key。
2. **全景会话与决策回放 (`/conversations`)**：跨租户全量对话检索、多轮意图轨迹回放、Agent 思考推理步骤下钻与耗时分析。
3. **风控审批审计 (`/audits`)**：Human-in-the-Loop 审批工单池，支持人工审核放行、风控驳回、理由追溯与状态实时对齐。
4. **人物画像与记忆 (`/personas`)**：支持 `Global`（身体基础尺码、过敏源）与 `Tenant`（特定品牌偏好）双层画像的查阅、修正与手工注记。
5. **知识库 RAG Studio (`/rag-studio`)**：SOP 文档上传分块、Anthropic Contextual 摘要提取与在线向量检索演练台（Playground）。
6. **技能与工具市场 (`/skills-tools`)**：统一管理平台内置核心工具（订单/退款/物流）、OpenAPI 3.0 动态导入工具与外部商户 SPI 工具。
7. **评测实验 (`/evals`)**：意图识别准确率、工具调用准度、安全防注入合规率与 Prompt 质量回归看板。
8. **计量计费 (`/billing`)**：多租户 Token 消耗统计、模型调用成本折算、充值额度与日限额熔断守卫。
9. **安全合规围栏 (`/guardrails`)**：动态配置 PII 隐私脱敏规则、敏感违禁词库、恶意提问检测与越权阻断策略。
10. **系统与 LLM 日志 (`/system-logs`)**：全链路 TraceID 关联、大模型调用耗时（Latency）、Token 详细构成与异常错误追踪。

---

## 4. 核心基础设施与安全底座 (Core Infrastructure)

### 4.1 任务执行图与人机协同审批 (LangGraph + HITL)

- **Plan-and-Execute 状态机**：通过 `triage` 意图分流 ➔ `planner` 规划 ➔ `merge` ➔ `executor` ⇄ `validator` 闭环执行，杜绝传统 ReAct 模式下的死循环与工具幻觉。
- **高危操作物理拦截**：当大模型规划退款、改派地址等涉及资金与敏感操作时，`ApprovalGatekeeper` 自动挂起任务并生成审批工单，等待管理员决议。

### 4.2 事务型发件箱与幂等重试 (Transactional Outbox)

- **原子事务保障**：管理员审批动作与 `approval_outbox_events` 事件写入处于同一个 PostgreSQL 本地事务中，彻底消除网络断开导致的“已审核但后台未唤醒”幽灵工单。
- **确定性幂等恢复**：后台 Worker 对超期未分发的事件进行指数退避自动重试，采用 `job_resume_${approvalId}` 确定性任务 ID 杜绝重复扣款。

### 4.3 双层用户画像与多租户上下文装配 (Dual-Tier Persona)

- **严格隔离边界**：
  - **Global Scope**：物理鞋码、布料过敏、默认收货手机等客观生理特征，跨商户共享体验。
  - **Tenant Scope**：Nike 独占优惠券、Adidas 专有会员等级等品牌偏好，跨商户绝对隔离，严防商户间竞品数据泄露。

### 4.4 参数化 SQL 编译与只读沙箱 (Parameterized SQL Sandbox)

- **工业级 Headless BI**：`NLMetricQueryEngine` 将自然语言指标查询编译为带 `$1`, `$2` 占位符的参数化 SQL，杜绝字符串拼装带来的注入漏洞。
- **沙箱隔离**：执行层强制开启 `SET TRANSACTION READ ONLY` 并施加 `3000ms` 超时与最大行数限制，保护主业务库稳定性。

### 4.5 上下文增益 RAG 检索 (Contextual RAG)

- **Anthropic 规范落地**：每个文本切片在入库前自动附带 50-80 词的全局情境摘要，并在数据库层强制施加 `WHERE business_id = :tenantId`，实现零跨租户污染与高精度召回。

### 4.6 开放商户 SPI 与动态工具市场 (Open Integration)

- **标准化对接契约**：定义开放商户 SPI 标准（`/spi/v1/orders/list`, `/spi/v1/orders/action` 等），商户可通过标准 HTTP 服务接入自有后台系统。
- **KMS 密钥加密**：商户通信密钥采用 AES-256-GCM 加密，基于租户 ID 进行 HKDF 密钥派生，在发起调用时 JIT 动态注入并在日志中脱敏。

### 4.7 Agent SOP 技能与 MCP 复合能力生态 (Composite Skills & MCP)

- **原子 Tool 升维为业务 Skill**：将原本离散的工具调用封装为符合标准业务 SOP（标准作业程序）的复合技能（如 `OrderRefundSkill`, `OrderAddressModificationSkill`, `ProductInquirySkill`），在 Skill 内部闭环完成参数校验、风控策略检查与结构化富卡片渲染。
- **极速直达通道 (Skill Fast-Track)**：意图分流引擎（`IntentTriageEngine`）在识别出高置信度意图且槽位齐备时，无需经过昂贵的 Planner 循环，直接调用 Skill 执行闭环，大幅压缩响应延迟与 Token 成本。
- **两层正交装配模型**：
  1. **角色工种维度**：不同子 Agent（导购、履约、风控）挂载专属技能集；
  2. **租户策略维度**：通过 `tenant_configs.skills_config` 动态开启/关闭 Skill 并自定义个性化免审阈值与 Prompt 策略。
- **NestJS 网关与控制台协同**：服务端提供 `/api/skills` 路由集群，Admin 技能中心支持对原生工具、OpenAPI、MCP Server 及 SOP Skill 进行统一可视化配置与热生效。

### 4.8 Agent Harness 运行底座与四层记忆体系 (Quad-Memory Hierarchy)

- **Harness 核心架构定义**：LLM 是非确定性的驱动核心，**Harness 则是包裹其外的确定性控制架与验证沙箱**。它负责**上下文装配与 Token 预算调度（Context Wallet）**、**确定性状态机循环（StateGraph Loop）**、**断点续跑（Temporal Replay）**以及**多层记忆治理**。
- **四层金字塔记忆体系**：
  1. **L0 工作记忆 (Working Memory)**：单轮状态机运行时上下文（`AgentStateAnnotation`），包含当前意图、规划子步骤与中间临时数据。
  2. **L1 短期会话记忆 (Short-term Memory)**：PostgreSQL `messages` 表，读取当前 `threadId` 的最近多轮对话，内置**自愈式反查加载机制（Self-Healing Short Memory）**避免断档。
  3. **L2 任务持久化记忆 (Task Memory)**：持久化当前任务状态（`TaskState`），支撑 Temporal 异步中断、审批挂起与跨节点精准续跑。
  4. **L3 长期偏好与情境记忆 (Long & Episodic Memory)**：
     - **LongMemory (事实偏好)**：用户长期偏好（如鞋码、布料过敏、偏好快递），经向量化沉淀入 `long_memory_facts`，支持 Global 与 Tenant 双层隔离；
     - **EpisodicMemory (重大事件)**：关键历史履约与售后事件（打标 `importance` 1-10），按余弦相似度（$\ge 0.55$）动态重召回。
- **记忆全生命周期更新流程**：
  - **写入流 (Write Pipeline)**：会话完成 ➔ Profiler 异步提取事实与重要性评分 ➔ 判定 Global/Tenant 作用域 ➔ Embedding 向量化入库 ➔ 坏向量自动剔除自洁。
  - **读取流 (Read Pipeline)**：`Promise.allSettled` 并行检索（Short + Long + Episodic + Contextual RAG）➔ 租户与用户范围过滤 ➔ Cosine 阈值门禁 ➔ 注入 Context Wallet。

### 4.9 生产级大模型综合安全风险评估与纵深防御 (Security & Guardrails)

针对 OWASP Top 10 for LLM Applications 深度落地四道纵深防御防线：

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       🛡️ 智能客服系统四大安全纵深防御防线                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. 提示词注入与越狱防御 (Prompt Injection & Jailbreak Defense)               │
│    - Triage 三层金字塔在入口过滤恶意越界提问 (out_of_scope)                  │
│    - 结构化 JSON 与 Markdown 严格语法隔离，防注入逃逸                        │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. 跨租户与横向越权防御 (Zero IDOR & Cross-Tenant Isolation)                │
│    - 严格禁止 LLM 自行指定 tenantId / userId                                 │
│    - 工具层与 RAG 层强制从 JWT / Session 上下文物理注入，DB 层 RLS 硬隔离     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. 资金与敏感操作防失控 (Excessive Agency & HITL Guardrails)                │
│    - SOP Skill 策略硬拦截：超过商户免审阈值一律阻断                          │
│    - Transactional Outbox 原子写入审批事件，强制管理员人工核准 (HITL)         │
├─────────────────────────────────────────────────────────────────────────────┤
│ 4. 数据库与远程代码执行沙箱 (SQL & Code Execution Sandbox)                  │
│    - Text-to-SQL 强制只读沙箱 (SET TRANSACTION READ ONLY) + AST 参数化编译  │
│    - 动态 OpenAPI / Webhook 开启 SSRF 私网 IP 阻断与超时熔断 (3000ms)        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.10 领域专职子智能体与隔离状态总线 (Multi-Agent Sub-Agents & State Bus)

针对电商多轮问答场景下上下文膨胀、工具过多导致 LLM 幻觉和注意力分散的问题，平台采用了**四位一体领域专职 Sub-Agents** 架构与**隔离状态总线（Namespaced State Bus）**：

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          分流路由与意图调度器 (Triage & Router Agent)                    │
│  - 0 个业务工具，纯轻量意图分类与槽位提取 (slotExtractor + Regex/LLM Deep Triage)       │
│  - 产出 activeDomainRole 并剪裁会话历史，杜绝跨领域上下文污染                           │
└───────────────┬────────────────────────┬────────────────────────┬──────────────────────┘
                │                        │                        │
                ▼                        ▼                        ▼
┌────────────────────────┐ ┌────────────────────────┐ ┌────────────────────────┐
│ 导购选品 Agent          │ │ 购物车与结算 Agent     │ │ 履约与售后 Agent       │
│ (Shopping Guide Agent) │ │ (Cart & Checkout Agent)│ │ (Order & Service Agent)│
├────────────────────────┤ ├────────────────────────┤ ├────────────────────────┤
│ • 专属工具集 (2-3个):   │ │ • 专属工具集 (2-3个):   │ │ • 专属工具集 (2-3个):   │
│   - searchProducts     │ │   - addToCart          │ │   - getOrderStatus     │
│   - compareProducts    │ │   - updateCartItem     │ │   - modifyAddress      │
│   - queryProductSkus   │ │   - getCartSummary     │ │   - applyRefund        │
│ • 多轮偏好挖掘与模糊澄清 │ │ • 跨 Agent 指代消解    │ │ • SOP 状态机合规校验   │
│ • 维护 guideContext    │ │ • 维护 cartContext     │ │ • HITL 审批挂起        │
│   (candidateProductIds)│ │   (lastModifiedItemId) │ │ • 维护 orderContext    │
└────────────────────────┘ └────────────────────────┘ └────────────────────────┘
```

- **隔离状态总线 (Namespaced State Bus)**：
  在 LangGraph 全局状态中划定 `guideContext`、`cartContext`、`orderContext` 独立命名空间，各子智能体只能读写其所属域的状态，避免上下文相互污染。
- **跨 Agent 指代消解与零损流转 (Cross-Agent Coreference & Handoff)**：
  当用户在导购 Agent 推荐多款商品后说“把第2件加入购物车”时，购物车 Agent 无需重读全量长文本，直接从 `guideContext.candidateProductIds` 确定性解析出目标 SkuId 并调用 `addToCart` 完成闭环。
- **Fast-Track 毫秒级直达与 BaseSkill 管线**：
  各领域 Agent 基于 `BaseSkill` 生命周期（`canHandle` ➔ `validate` ➔ `execute` ➔ `postExecute`），在命中高置信意图时毫秒级旁路直达，直接输出富文本卡片（`RichCardBlock`）。

### 4.11 多租户 SQL 物理层下推隔离与越权防御 (SQL Push-Down Tenant Isolation)

- **物理下推而非内存过滤**：全平台所有底层数据仓储与风控核签方法（如 `ConversationRepository.getConversationTimeline`、`ApprovalGatekeeper.listPendingApprovals` 等）强制将 `business_id` 参数下推至 PostgreSQL 物理 SQL 约束（`WHERE business_id = $1`），彻底杜绝无限制全表加载后在应用层做 JavaScript 过滤带来的越权漏洞（IDOR）与内存泄漏风险。
- **租户参数白名单校验与防御**：NestJS 全局管道开启 `ValidationPipe({ forbidNonWhitelisted: true, whitelist: true, transform: true })`，严格阻断未知参数与租户伪造，保障多租户物理与逻辑边界的绝对安全。

### 4.12 实时协同接管与 SSE 流式弹性回放 (Live Desk Takeover & SSE Resiliency)

- **WebSocket 双向即时坐席接管网关 (`ConversationGateway`)**：
  基于 NestJS WebSocket 与 Redis Pub/Sub 实现分布式会话接管。坐席端一键发起 `takeover_conversation`，会话状态机原子跃迁至 `human_takeover` 并暂停 AI 自动回复；释放时通过 `release_takeover` 瞬间无缝归还 AI 托管。
- **SSE 断线重连与 `Last-Event-ID` 跨连接精准回放**：
  `ChatService` 引入跨连接的 Job 级事件缓存队列（`jobEventStore`）。当客户端在流式传输过程中因网络波动重连并携带 `Last-Event-ID: <seq>` 时，网关自动从持久化缓冲池中重放掉线期间遗漏的思考步骤（`thought`）、工具调用（`tool`）、富卡片（`cards`）与最终结果（`result`），保障多模态对话流的 100% 幂等与无缝连续性。

---

## 5. 质量保障与全自动化测试 (Quality & Automation)

项目采用金字塔型测试架构，全面覆盖单测、集成测试与端到端自动化：

```bash
# 运行全部单测与集成测试
bun test

# 运行 admin 控制平面独立单元与集成测试
bun test apps/admin/tests/

# 运行 server 网关 SPI 接口测试
bun test apps/server/test/

# 运行 Playwright 浏览器端到端 E2E 自动化测试
bun run test:e2e
```

---

## 6. 开发与部署命令 (Quick Start)

### 快速启动开发环境

```bash
# 1. 安装依赖
bun install

# 2. 启动所有服务 (Web, Admin, Server, Engine, Merchant)
bun run dev

# 3. 独立启动各应用
bun --filter admin dev    # 启动 SaaS 控制平面 (http://localhost:3001)
bun --filter web dev      # 启动用户客服前端 (http://localhost:3000)
bun --filter server dev   # 启动 NestJS 后端网关 (http://localhost:4000)
bun --filter merchant dev # 启动独立演示商城 (http://localhost:3002)

# 4. 全量代码编译与类型检查
bun run build

# 5. 代码风格检测与格式化
bun run lint
```

---

## 📄 历史版本说明

如需查阅早期初代 Next.js 单体架构的设计与历史提交，请检出并查看 `v1-main` 分支。
