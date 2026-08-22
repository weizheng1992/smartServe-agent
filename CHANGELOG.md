# 🚀 CHANGELOG.md

系统中所有重要升级、重大架构重构、Breaking Changes 以及功能演进均记录在案。

---

## [1.10.0] - 2026-08-22

### 🌟 Major Highlights (重大亮点)

- **PostgreSQL 确定性角色时序排序与历史对话防错乱引擎 (Deterministic Message Ordering & Monotonic Clock)**:
  - 彻底根除刷新页面后对话历史次序颠倒（AI 回复跑到用户提问前）的顽疾。
  - 在 `packages/db/src/client.ts` 物理查询层引入确定性角色权重排序：`ORDER BY timestamp ASC, CASE role WHEN 'system' THEN 1 WHEN 'user' THEN 2 WHEN 'assistant' THEN 3 ELSE 4 END ASC, id ASC`，消除同一毫秒并发写入导致 UUID 字典序随机颠倒的缺陷。
  - 在 `packages/engine/src/memory/shortMemory.ts` 引入基于逻辑时钟的角色单调递增时间戳生成机制（`getMonotonicTimestamp`），保证 `assistant` 响应在时钟逻辑上严格晚于 `user` 提问。
  - 通过 `packages/engine/tests/messageOrdering.test.ts` 并发时序验证，确保全场景历史记录 100% 严格按先后交互顺序呈现。
- **SaaS 多租户品牌身份物理锚定与动态脱敏 (Multi-Tenant Brand Identity Anchor & JIT Sanitization)**:
  - 修复多租户会话中商户品牌（如 Nike、Adidas）在历史消息中被降级为 `[ECOMMERCE]` 占位符的问题。
  - 强化 `db.createThread` 租户保护屏障：现有商户会话拒绝被未指定或默认的 `ecommerce` 身份覆盖。
  - 在 `/api/chat/messages` 接口层引入 `sanitizeTenantResponse`，在历史记录拉取阶段结合会话所属商户动态清洗品牌心智。
- **输入框生命周期管理与即时清空机制 (Chat Input State Lifecycle & Instant Clearing)**:
  - 修复发送消息后输入框依然残留上一轮文本的交互缺陷，解耦表单提交与发送逻辑。
  - 在 `ChatArea.tsx` 的 `onSubmit` 与 `useChatMessages.ts` 的 `handleSend` 中实现状态无条件清空，并清空附件图片列表。
  - 增加 `apps/web/tests/chatInputState.test.ts` 单元测试验证输入状态生命周期。
- **人工客服接管生命周期与乐观加载态隔离 (HITL Takeover Lifecycle & State Isolation)**:
  - 修复转人工后用户继续提问导致界面永久卡在“正在全速运行多模态有向有环图节点，智能调用工具链中...”以及 AI 错误抢答的缺陷。
  - 在 `useChatMessages.ts` 收到 `isHumanActive: true` 时立即清理乐观加载态（`isLoading: true` / `pending-job`），并调用 `loadHistory(force=true)` 同步真实数据库消息。
  - 严格保障人工客服接管期间（`status = 'waiting'`）用户消息直通数据库并实时同步，直到人工专员明确点击“🏁 结束人工服务 (切回 AI)”（`status = 'resolved_by_human'`）后才平滑恢复 AI 智能调度。
- **运行时连接池单例化与 HMR 缓存防护 (GlobalThis Singleton Pool Management)**:
  - 修复 Next.js 热重载（HMR）过程中反复建立物理 PostgreSQL 连接池、Redis 客户端和 Temporal Client Promise 的问题，统一通过 `globalThis` 实现单例生命周期管理。

---

## [1.9.0] - 2026-08-21

### 🌟 Major Highlights (重大亮点)

- **商城全功能数据库体系与领域服务 (Comprehensive E-Commerce Schema & Mall Domain Service)**:
  - 物理构建高标准 SaaS 关系型商城数据库结构：
    - `user_addresses`: 用户多地址簿（默认地址、详细门牌、收货人与联系电话）；
    - `product_skus`: 商品多规格属性（尺码、颜色、SKU 编码、库存与差异化价格）；
    - `logistics_packages`: 订单履约包裹表（多包裹拆单履约、承运商与主运单号）；
    - `logistics_tracks`: 物流时序轨迹流水（时间戳、物理节点站点、派送状态与描述）；
    - `product_reviews`: 用户商品评价与晒单（星级打分、文本评论与图片证据）；
    - `after_sale_tickets` & `after_sale_logs`: 售后服务工单与流转状态机跟踪。
  - 封装 `MallDomainService` 领域服务，提供标准查询与状态流转接口。
- **意图-槽位状态机与缺失参数即时反问机制 (Intent-Slot State Machine & Fast-Path Clarification)**:
  - 实现结构化槽位与意图抽取器 `SlotExtractor`，严格定义高风险业务必填槽位映射表 `REQUIRED_SLOTS_MAP`（如修改收货地址必须具备 `orderId` 与 `newAddress`）。
  - 在 `IntentTriageEngine` 阶段引入槽位缺失拦截守卫，参数不足时毫秒级生成即时精准反问并写入 `TaskMemory` 多轮上下文记忆；参数补齐后高置信度放行直达 DAG 调度，彻底阻断由于缺少参数导致的自旋与大模型幻觉。
  - 接入 Promptfoo 专属槽位评测集 `slot-clarification.json` 与 `slotClarification.scorer.ts` 自定义评分器，评测通过率 100%。
- **Temporal 真实编排实时状态 SSE 桥接与防假死架构 (Temporal SSE Real-Time Status Stream)**:
  - 重构 `/api/chat/[jobId]/stream` 路由，在真实 Temporal 模式下建立 300ms 毫秒级 `currentStatusQuery` 与 `currentPlanQuery` 轮询推送机制，将底层节点执行状态实时桥接至 Web UI。
  - 在 LangGraph `buildAgentGraph` 及 Temporal `agentWorkflow` 中统一 `isBypass` 判定守卫（`state.output` 存在或 `bypass_step`），保证槽位即时反问与规则旁路毫秒级直达 `finishNode`，避免误入 Planner 自旋。
- **泛订单查询极速直达与批量富媒体卡片合成 (Fast-Path Order Listing & Rich Card Batching)**:
  - 细化泛查单意图与单笔物流追踪正则边界，消除“我的订单”被误拦截为缺失单号追问的缺陷，极速直达 `listUserOrders` 调度。
  - 扩展 `CardSynthesizer` 引擎支持 `result.orders` 批量订单交互卡片生成（查看物流轨迹、申请退款按钮及智能快捷回复胶囊），并内置多租户演示订单自动自愈机制。
  - Monorepo 全量 122 项单元与集成测试 100% 绿色通过（578 个断言）。

---

## [1.8.0] - 2026-08-21

### 🌟 Major Highlights (重大亮点)

- **Text-to-SQL 与 Headless BI 指标语义注册表体系 (Metric Semantic Registry v2)**:
  - 落地 `MetricDefinition v2` 契约标准，将 SQL 聚合公式、动态模板、业务规则约束、口语同义词、歧义冲突组（`conflictGroup`）、排序及展示单位结构化声明配置，从根源上杜绝大模型口径幻觉与硬编码 `if/else`。
  - 预置商场多维指标元数据字典（GMV 总销售额、出货销量件数、净毛利润收益、单品毛利率、滞销积压库存预警）。
  - 实现 `MetricSemanticResolver` 智能指标匹配器，自动识别自然语言同义词与冲突组（如 GMV 流水 vs 出货件数 vs 净毛利润 vs 毛利率）。
- **六大正交解耦 NL2SQL 查询语法树解析与动态编译器 (`packages/tools/src/nlQuery/`)**:
  - `TextNormalizer`：入口前置清洗语气词与虚词（“帮我/麻烦看一下/给我展示/对比看看”等），保护语义纯净度。
  - `TimeRangeResolver`：独立解析时序范围（“近30天/上个月/近7天/今年”），自动输出参数化 PostgreSQL 时间过滤子句。
  - `OrderLimitResolver`：解析“销售额最低/倒数/最少”等反向排序指令并动态改写 `directionOverride`，同时精准提取 TopN 数量限制。
  - `DimensionResolver`：动态解析分组维度（“按品类看/按商品维度”），解耦指标与 GROUP BY 物理列。
  - `FilterResolver`：解析“库存大于500/价格低于200/品类是鞋类”等多维数值与枚举过滤条件。
  - `NLQueryCompiler`：结合多租户上下文、负责人 `managerId` 与 AST 语法树动态安全渲染参数化物理 PostgreSQL 语句，支持防除零安全保护。
- **商场物理数据库扩展与多维分析服务 (`OrderDomainService.queryProductRanking`)**:
  - PostgreSQL 物理迁移：`products` 表扩充 `manager_id`、`category`、`cost_price` 字段，`order_items` 表扩充 `cost_at_purchase`（下单成本快照，防后续商品改价失真）。
  - 注入高保真商场种子数据（覆盖 Vaporfly 顶级竞速鞋、飞马跑鞋、长筒袜等不同销量/流水/毛利特性的商品与订单）。
- **声明式槽位消歧引擎与富交互卡片闭环 (`SlotDisambiguationEngine` & `ProductRankingCard`)**:
  - 实现通用槽位消歧引擎，结合 LongMemory 用户画像与 Default 策略推荐最佳指标。
  - `CardSynthesizer` 自动合成带有金银铜牌徽章、单价、累计销量、GMV 流水、净毛利润与毛利率的 `ProductRankingCard`。
  - 在卡片底部自动挂载 Quick Replies 一键切换口径胶囊（💰 按总销售额 / 📦 按出货销量 / 📈 按净毛利润 / 🎯 按单品毛利率 / ⚠️ 排查滞销库存），实现人机交互与口径切换闭环。
- **Promptfoo 质量评测与 Monorepo 全量测试保障**:
  - 新增 `eval/scorers/metricDisambiguation.scorer.ts` 与 `eval/testCases/ecommerce/metric-disambiguation.json` 评测用例集并在 `promptfooconfig.yaml` 中注册；
  - Monorepo 全量 100 个单元与集成测试 100% 绿色通过（494 个断言）。

---

## [1.7.0] - 2026-08-20

### 🌟 Major Highlights (重大亮点)

- **多模态视觉感知与智能破损定责系统 (Multimodal Vision & Damage Assessment)**:
  - 引入 `VisionAnalyzerService`，在 Triage 首层直接支持图文多模态意图识别、快递面单 OCR 提取（运单号/订单号）与商品破损瑕疵智能定级（`negligible` / `minor` / `severe`）。
  - 内置手机号、身份证、银行卡 PII 敏感信息脱敏过滤器，并具备 1500ms 视觉超时与启发式降级兜底。
- **富交互结构化卡片与统一渲染引擎 (Rich Interactive Cards & Synthesizer)**:
  - 新增 `CardSynthesizer` 引擎与统一协议标准（`order_card`、`tracking_timeline`、`refund_confirmation`、`damage_assessment`、`quick_replies`）。
  - 在 `packages/ui` 中构建原生 SVG 图标的高保真卡片组件族与 `RichCardRenderer`，支持一键查看物流、申请退款、动态快捷回复胶囊交互。
- **图片安全上传端点与客户端多图预览 (Safe Image Upload & Client Preview)**:
  - 新增 `/api/chat/upload` 统一接口，强制校验 MIME Type（JPG/PNG/WebP/GIF）与 10MB 大小边界，落盘至持久化目录。
  - 前端输入区集成“📎 图片上传/粘贴”预览条与快捷移除卡片。

---

## [1.6.0] - 2026-08-20

### 🌟 Major Highlights (重大亮点)

- **SaaS 商户自主入驻与配置中台 (Self-Service Tenant Hub & IAM)**:
  - 引入 `tenants`、`tenant_members`、`tenant_configs` 与 `tenant_tools` 实体，规范单层商户模型 (`businessId` 命名空间) 与 `Owner` / `Admin` / `Agent` 三级 RBAC 权限隔离。
  - 实现提示词与品牌心智配置的草稿调试（`draft`）与生产发布（`published`）双状态生命周期。
- **商户 API 凭证安全加密与运行时 JIT 脱敏 (Secrets KMS & JIT Injection)**:
  - 基于 Node.js 原生 `crypto` 与 RFC 5869 HKDF，利用主密钥与租户 ID 派生独立密钥，实施 `AES-256-GCM` (`iv:authTag:ciphertext`) 高强加密存储。
  - 动态工具调用时实行 JIT 即时解密注入 Header，全链路脱敏 Pino 日志、Langfuse Span 与 SSE 推送流。
- **OpenAPI 3.0 动态工具工厂与 SSRF 运行时安全沙箱 (Dynamic Tools & SSRF Guard)**:
  - 动态解析 OpenAPI JSON 并生成 Zod Schema 校验器，自动将 `x-requires-approval` 与变更路径路由至 HITL 待审批队列。
  - 内置 DNS 预解析与私网网段（`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.169.254`）硬拦截 SSRF 运行时沙箱，并施加 8 秒物理超时熔断。
- **知识库多格式异步切片与 Contextual RAG 摄入流水线 (Document Ingestion Pipeline)**:
  - 实现递归段落边界分块（~600 tokens 目标大小，100 tokens 重叠）并自动生成 Anthropic 标准情境摘要，批量注入 PostgreSQL `rag_documents`。
- **租户管理与配置 REST API 路由**:
  - 新增 `/api/tenant/onboard`、`/api/tenant/config`、`/api/tenant/tools` 与 `/api/tenant/knowledge/upload` 统一接口。

---

## [1.5.0] - 2026-08-20

### 🌟 Major Highlights (重大亮点)

- **纯物理真实 PostgreSQL 数据库架构 (Single Source of Truth)**: 彻底移除了 600+ 行内存模拟库（`FakePool`）及复杂的 SQL 正则匹配与降级分支，系统所有读写操作均直连物理真实 PostgreSQL 数据库与 Drizzle ORM，彻底杜绝数据脱节与幽灵数据。
- **聊天记录单调时序与会话级强隔离 (Message Ordering & Session Isolation)**:
  - 在 `ShortMemory` 与 `AgentMemoryEngine` 中引入单调递增时间戳与严格串行入库，数据库查询增加 `ORDER BY timestamp ASC, id ASC`，彻底解决高频与并发写入下刷新页面消息时序颠倒混乱的问题。
  - 重构前端 `useChatMessages` 与 `useChatThreads`，通过活跃会话 Ref 竞态防护拦截迟到异步响应，并在新建与切换会话时立即重置界面为默认欢迎语，彻底消除旧会话历史残留穿透。
- **公共标准订单创建领域服务 (`createOrder`)**: 在 `OrderDomainService` 中新增并暴露了标准 `createOrder` 工具，自动关联用户会话、多租户（SaaS Tenant）归属与订单明细条目，并在落盘后自动同步清除 Redis/本地缓存。
- **Admin 控制台客服介入 IM 工作台统一 (`HumanChatModal`)**: 抽离统一的 `packages/ui/src/components/chat/` 模块，配置 Tailwind CSS v4 `@source` Monorepo 扫描规则，彻底解决 Admin 工作台独立编译下的弹窗样式错位变形。
- **意图分流防误拦截 (Zero False-Positive Refund Interception)**: 优化 `intentTriageEngine`、`executorFastPath` 与 `stepExecutionEngine`，消除纯订单查询被误拦截为退款流程的逻辑缺陷。

### 🏗️ Major Refactoring (重大重构)

- **移除内存数据库模拟器 (`b05abd4`)**: 彻底删除了 `packages/db/src/fakePool.ts`，简化 `packages/db/src/client.ts` 使得所有 API、Agent 与工具直连真实 `pg.Pool` 连接池。
- **统一 HITL 审批中台组件与领域服务 (`11127ff`, `abd1832`)**: 对 HITL 审批工单、人工客服 IM 接管弹窗、订单领域服务及跨包类型进行了全量模块化收敛与编译修复。

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
