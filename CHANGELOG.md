# 🚀 CHANGELOG.md

系统中所有重要升级、重大架构重构、Breaking Changes 以及功能演进均记录在案。

---

## [1.4.0] - 2026-08-19

### 🌟 Major Highlights (重大亮点)

- **子任务并行执行器 (Parallel Subtask Executor)**: 在 `StepExecutionEngine` 中实现了基于 `Promise.all` 的无依赖子任务并行调度器，多意图复合查询执行延迟物理降低 50%+。
- **PII 敏感数据物理脱敏拦截器 (PII Scrubber Middleware)**: 在 `packages/tools` 中上线递归敏感数据脱敏切面，自动掩码手机号、身份证、银行卡号与邮箱，保障日志与 Trace 架构合规。

### 🚀 Features & Enhancements

- **并发子任务并行调度 (`cb52316`)**: 重构 `StepExecutionEngine`，自动检测 Fast-Path 独立子任务队列并通过 `Promise.all` 并发极速调起工具，极大缩短用户等待时间。
- **工具链 PII 脱敏切面 (`cb52316`)**: 统一封装 `registerTool` 执行层，所有工具输入/输出参数自动进行 PII 物理数据掩码。
- **TTFT 测速与压测大盘升级 (`cb52316`)**: 升级 `scripts/load-test.ts`，增加流式 SSE 首字响应延迟 (Time To First Token, TTFT) 检测与多租户并发测试能力。

---

## [1.3.0] - 2026-08-14

### 🌟 Major Highlights (重大亮点)

- **多意图分析与 Fast-Path 多步骤直达**: 实现了对多意图（如“查询物流+申请退款”）的精准识别、主次意图加权（Primary/Secondary Weighting）以及槽位提取，并在关联订单号时提供秒级极速直达通道（无需 LLM 规划消耗）。

### 🚀 Features & Enhancements

- **类型升级 (`30d6c25`)**: 为 `IntentResult` 增加了 `type` 与 `entities` 槽位，使分类图节点具备复合诉求提取能力。
- **极速调度优化 (`30d6c25`)**: 拓展 Planner 节点的 Fast-Path，支持复合意图直接组装多步骤子任务 DAG 链，将首字与步骤生成延迟降低 1.5s ~ 2.0s。

---

## [1.2.0] - 2026-08-12

### 🌟 Major Highlights (重大架构升级)

- **深模块门面重构 (Deep Module Facade Clean Up)**: 将原本膨胀的单体模块彻底拆解，提升系统测试性与可维护性。
- **Anthropic Contextual RAG 热更新管线**: 构建集 Markdown Chunking、Contextual Summary 提取、YAML Frontmatter 标注与零样本（Zero-shot）分类于一体的 RAG 数据入库管线。

### 🏗️ Major Refactoring (重大重构)

- **四层记忆统一门面 (`AgentMemoryEngine`) (`7aae5be`)**: 封装 Short、Long、Task、Episodic 四层记忆，实现单次并行获取 (`gatherContext`) 与增量并发归档 (`recordTurn`)。
- **网络流与 UI 渲染解耦 (`AgentStreamClient`) (`7aae5be`)**: 抽离 SSE 订阅客户端，彻底消除 React 渲染树对 EventSource 生命周期的依赖。
- **双模工作流统一调度器 (`WorkflowOrchestrator`) (`7aae5be`)**: 统一 Temporal 生产引擎与本地 LangGraph 极速模拟器的调度与降级逻辑。
- **安控网关拆分 (`StepExecutionEngine` & `ApprovalPolicyEngine`) (`7aae5be`)**: 将 800+ 行单体执行节点解耦为任务执行引擎与金融红线校验网关。
- **数据库仿真隔离 (`FakePool`) (`7aae5be`)**: 从 Drizzle 客户端解耦，提供隔离的 12+ 张关系型表的内存 SQL 仿真。

### 🚀 Features

- **SOP 生产上线标准检查清单 (`687f9dc`, `029e6f7`)**: 在 `README.md` 中集成包含数据库 Migration、Quotaguard 防刷、CircuitBreaker 熔断与 20 并发高吞吐压测脚本的生产上线 SOP 指南。

---

## [1.1.0] - 2026-08-11

### 🌟 Major Highlights (重大重构)

- **全局类型安全与领域仓储隔离**: 彻底剥离全代码库中的 Loose `any` 隐式类型，提炼独立的 `packages/types` 基础包。
- **人工客服 IM 实时接管系统**: 实现 LLM 断路触发、一键人工接管对话（`start_human_takeover`）及对话流安全挂起与恢复。

### 🏗️ Refactoring

- **独立类型共享包 (`packages/types`) (`d2e058f`, `d1a168c`, `b399025`)**: 按 `agent`, `approval`, `config`, `log`, `db`, `event`, `observability`, `tool` 进行模块化强类型声明。

### 🚀 Features & Fixes

- **断路器与人工客服 IM (`78b1e42`)**: 支持客服主管在控制台发起实时 IM 接管，安全打断 AI 决策，并在完成后平滑恢复 AI 智能应答。
- **Fast-Path 规划旁路 (`825b6ae`)**: 实现单意图查询/退款的零 LLM 消耗单步计划合成。

---

## [1.0.0] - 2026-08-10

### 🌟 Major Milestone (1.0 稳定版发布)

- **金融级多租户隔离与账单审计上线**: 正式落地 SaaS 多租户 SQL 物理隔离、Redis SETNX 分布式并发锁与高精度财务算力计费大盘。

### 🚀 Features

- **SaaS 物理隔离与分布式锁 (`537f794`)**: ORM 物理附加 `business_id` 过滤；引入 Redis SETNX 分布式并发防重入锁与 5s 短 TTL 内存降级锁。
- **算力审计大盘 (`537f794`)**: 异步写入 `session_metrics` 账单，提供毫秒级决策时效与 Autopilot 放行率统计。

---

## [0.9.0] - 2026-08-04

### 🔧 Stability & Critical Fixes (稳定性加固)

- **管道缺陷修复 (`66f2e73`)**: 修复包含高价值订单地址变更审核拦截、引用指针失效、死循环熔断以及数据库降级崩溃等 7 个关键 Pipeline Bug。
- **滑动历史窗口与容器防冻保护 (`eb26e4d`)**: 实现对话历史滑动窗口截断，增加 Serverless 容器解冻保护（`waitUntil`）。

---

## [0.8.0] - 2026-07-30

### 🚀 Performance & Multi-Turn Intelligence (性能与上下文优化)

- **Triage 极速优化 (`9567a8a`)**: 引入全局向量缓存（`embeddingCache`）与 Anchor 例句批量向量预加载，大幅提升意图分类速度。
- **上下文感知精判 (`8958721`, `ba10032`)**: 升级大模型意图分类 Prompt，使其具备结合前 4 轮历史上下文的深层语义理解能力。

---

## [0.7.0] - 2026-07-29

### 🏗️ Workspace Modularization (工作空间与 UI 重构)

- **解耦独立应用 (`0075c26`, `e086c89`)**: 将管理控制台（Admin）与用户主站（Web）迁移至 `app/home`，拆分为高内聚组件与 Hooks。
- **共享 UI 基础设施 (`da78d6d`, `f758aaa`)**: 抽离独立的 `packages/ui` 基础包，统一 Lucide Icons 图标导出与 Tailwind 样式模板。
- **HITL 轮询感知器 (`286037d`, `916abe5`)**: 实现前端高保真人工审核工单同步感知传感器，彻底解决多端并发状态竞争问题。

---

## [0.6.0] - 2026-07-28

### 🛡️ Security & Profiling (安全红线与用户画像)

- **IDOR 水平越权拦截 (`e9dc57f`)**: 物理拦截跨用户访问他人订单的 IDOR 漏洞。
- **异步画像 Agent (`5544d78`)**: 引入后台异步 `UserProfileAgent`，自动从多轮对话中提炼客户消费偏好与尺码卡片。
- **多租户物理沙箱 (`cc61d67`)**: 实现知识库向量检索的物理租户隔离沙箱与图级别死循环硬熔断。

---

## [0.5.0] - 2026-07-27

### 🚀 Admin Audit Desk & Advanced RAG (管理大屏与高级 RAG)

- **独立 Admin 中台 (`64698b6`, `6d74046`)**: 创建 Next.js 独立 `apps/admin` 管理工作区，部署可视化人工核签与审核大屏。
- **高级数学 RAG 混合检索 (`1a81b23`)**: 废弃简单关键字匹配，实现 Portable BM25 算法与 Reciprocal Rank Fusion (RRF k=60) 倒数排名融合。
- **自动化 Promptfoo 评测平台 (`5e53191`, `5c59226`)**: 搭建涵盖 Prompt 越狱防范、工具调用准确率与 LLM-as-a-judge 的自动化评估套件。

---

## [0.1.0] - 2026-07-24

### 🐣 Initial Project Release (项目初始发布)

- **智能客服中台初始化 (`3939a76`)**:
  - 核心 LangGraph Agent 决策图 (`triage` → `planner` → `merge` → [`executor` ⇄ `validator`] → `finish`) 构建。
  - 人工核签与认知回溯（HITL & Cognitive Backtracking）机制落地。
  - PostgreSQL + Drizzle ORM + Redis 架构搭建。
  - 支持 Nike / Adidas 多商户动态配置与退款免签额度防线。
