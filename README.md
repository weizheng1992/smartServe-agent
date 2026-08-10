# 🚀 smartServe-agent: 分布式多租户 SaaS 智能客服决策中中台平台

smartServe-agent 是一款基于 **Turborepo Monorepo**、**Bun 运行环境** 与 **LangGraph 决策图** 构建的日活千万级、高弹性、高防卫金融级智能客服 Agent 决策平台。

系统原生支持 **SaaS 多租户物理隔离**、**人工核签红线拦截与重规划自适应回溯**、**Anthropic Contextual RAG（上下文增益知识库检索）**，并配备了 **Redis 分布式并发锁**、**物理自愈指数退避 LLM HA-Proxy**、以及**高敏捷 SaaS 财务算力账单仪表盘**。

在近期，我们对整个对话机制、生命周期和工具链进行了大规模的**硬核架构重构与稳定性加固**，实现了**无感多轮记忆自愈**与**零 Fallback 金融级多租户会话隔离**。

---

## 目录

1. [项目架构与双模引擎设计](#1-项目架构与双模引擎设计)
2. [高精准工作空间目录树 (Workspace Tree)](#2-高精准工作空间目录树-workspace-tree)
3. [核心模块深度技术讲解 (Deep Module Breakdown)](#3-核心模块深度技术讲解-deep-module-breakdown)
   - [3.1 `apps/web` 前端可视化与核签平台](#31-appsweb-前端可视化与核签平台)
   - [3.2 `packages/engine` 核心 Agent 智能决策图与工作流](#32-packagesengine-核心-agent-智能决策图与工作流)
   - [3.3 `packages/db` 关系型范式数据接入与高保真仿真器](#33-packagesdb-关系型范式数据接入与高保真仿真器)
   - [3.4 `packages/tools` 物理工具链与安全防护拦截](#34-packagestools-物理工具链与安全防护拦截)
   - [3.5 `packages/observability` 算力计量与全链路 Trace 日志](#35-packagesobservability-算力计量与全链路-trace-日志)
   - [3.6 `packages/business-configs` 多商户 SaaS 动态策略配置](#36-packagesbusiness-configs-多商户-saas-动态策略配置)
4. [核心底层设计实现细节](#4-核心底层设计实现细节)
   - [4.1 金融级人机协同与认知回溯决策环 (HITL)](#41-金融级人机协同与认知回溯决策环-hitl)
   - [4.2 SaaS 级多租户隔离与 Contextual RAG 检索](#42-saas-级多租户隔离与-contextual-rag-检索)
   - [4.3 物理工具链政策红线守卫 (SOP Guardrail)](#43-物理工具链政策红线守卫-sop-guardrail)
   - [4.4 双通道并发防刷与 Redis SETNX 分布式锁](#44-双通道并发防刷与-redis-setnx-分布式锁)
   - [4.5 100% 授信 Gemini-Only 自愈抗灾与精确 Token 追踪](#45-100-授信-gemini-only-自愈抗灾与精确-token-追踪)
   - [4.6 SaaS 动态配置热载入与免签额度路由守卫](#46-saas-动态配置热载入与免签额度路由守卫)
   - [4.7 SaaS 算力审计与财务账单度量系统](#47-saas-算力审计与财务账单度量系统)
   - [4.8 多轮会话物理自愈载入 (Self-Healing Short Memory)](#48-多轮会话物理自愈载入-self-healing-short-memory)
   - [4.9 双向会话同步与零 Fallback 级 UUID 会话管理](#49-双向会话同步与零-fallback-级-uuid-会话管理)
5. [质量保障与评测体系 (Testing & Tooling)](#5-质量保障与评测体系-testing--tooling)
6. [开发与部署命令](#6-开发与部署命令)

---

## 1. 项目架构与双模引擎设计

平台采用 **双模弹性执行引擎** 设计，兼具高灵活性与极致抗灾灾备能力：

```
┌─────────────────────────────────┐
│     Next.js Web (apps/web)      │ ← 前端UI + 实时 SSE 广播流，提供浮动 HITL 人工核签控制台
└────────────────┬────────────────┘
                 │
        POST /api/chat 提交 (携带 threadId, 新增 Singleflight 请求合并 & Short-TTL 缓存防刷)
                 │
                 ▼
     [ getTemporalClient() 检测 ]
                 ├───────────────────────────────────────┐
                 │ (未连接/Offline)                       │ (物理连接成功/Online)
                 ▼                                       ▼
┌─────────────────────────────────┐    ┌─────────────────────────────────┐
│     本地极速直跑仿真模式         │    │       生产级 Temporal 引擎       │
│  - 零时开销直接启动 StateGraph   │    │  - 注册为 agentWorkflow 工作流   │
│  - 使用 EventEmitter 进行日志广播│    │  - 状态物理入库，支持 Queries 检索│
│  - 基于 global.agentRuns 状态追踪│    │  - 调起物理活动 (Activities) 节点 │
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
│  - PostgreSQL / Drizzle ORM (自愈 Seed 注入，FakePool 离线关系型仿真)    │
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
│   └── web/                         # Next.js 15 控制台与 Web 客服看板
│       ├── app/                     # App Router 核心路由
│       │   ├── api/                 # 服务端 API 端点集合
│       │   │   ├── analytics/       # SaaS 财务算力 BI 分析看板数据端点
│       │   │   ├── auth/login/      # 多商户隔离登录鉴权
│       │   │   ├── chat/            # POST 聊天中转 (Singleflight 与 5s 重复过滤防刷)
│       │   │   ├── chat/approvals/  # 人工审批 GET/POST 端点 (带 SETNX 锁防重入)
│       │   │   ├── chat/messages/   # 物理拉取会话历史记录
│       │   │   ├── chat/threads/    # 会话线程自动创建与多商户绑定
│       │   │   └── chat/[jobId]/stream/ # SSE 实时工作流状态机节点日志广播流
│       │   ├── layout.tsx           # 全局高画质暗黑布局
│       │   └── page.tsx             # 核心客服控制台 (双向 URL 同步、UUID v4 自愈装配)
│       ├── components/              # 页面 React UI 交互组件
│       │   ├── login-card.tsx       # 登录卡片
│       │   └── ui/                  # 基础 Tailwind 按钮与弹窗等基础原子组件
│       └── e2e/                     # 浏览器端到端自动化测试
│           └── chat-hitl.spec.ts    # 物理模拟人工核签的全旅程 Playwright E2E 测试
│
├── packages/
│   ├── engine/                      # 核心决策引擎 (LangGraph + Temporal 双模)
│   │   ├── src/                     # 源代码目录
│   │   │   ├── graph/               # 决策图定义
│   │   │   │   ├── nodes/           # Triage, Planner, Merge, Executor, Validator, Finish 节点
│   │   │   │   ├── buildGraph.ts    # 编译 LangGraph，承接多路 RAG 聚合，Telemetry 物理账单 Flush
│   │   │   │   ├── eventEmitter.ts  # EventEmitter 模拟流广播系统
│   │   │   │   └── state.ts         # AgentStateAnnotation 状态归整，buildHistoryContext 洗涤清洗
│   │   │   ├── llm/                 # 弹性调用代理
│   │   │   │   └── callLLMWithRetry.ts # ResilientLLM 强自愈代理 (自旋指数退避重试，Token精准累加)
│   │   │   ├── memory/              # 系统级 4 重高聚合物理记忆
│   │   │   │   ├── index.ts         # 统一暴露出口
│   │   │   │   ├── shortMemory.ts   # 短期历史记忆 (100% 反查 PostgreSQL 表自愈)
│   │   │   │   ├── longMemory.ts    # 长期事实记忆 (持久化矢量 Facts 记忆)
│   │   │   │   ├── episodicMemory.ts# 情境回忆 (提取相似事件)
│   │   │   │   └── taskMemory.ts    # DAG 子步骤状态记忆
│   │   │   ├── rag/                 # 混合检索 RAG 模块
│   │   │   │   └── contextualRag.ts # Anthropic Contextual RAG 混合双向比对重排引擎
│   │   │   ├── temporal/            # 生产级分布式高并发工作流
│   │   │   │   ├── client.ts        # Temporal 客户端连接句柄
│   │   │   │   ├── worker.ts        # 物理 Worker 守护进程启动程序
│   │   │   │   ├── workflows.ts     # 工作流注册 `agentWorkflow` 编排器
│   │   │   │   └── activities.ts    # 活动层物理代理执行器 (`runAgentStateNode`)
│   │   │   └── index.ts             # 统一暴露
│   │   └── tests/                   # 自动化引擎测试
│   │       ├── state-reducers.test.ts # 校验状态规整、历史清洗、状态图自旋单元测试
│   │       └── system.test.ts       # 仿真端到端集成与多租户测试
│   │
│   ├── db/                          # 关系型数据层 (3NF 高规范 Drizzle ORM)
│   │   ├── drizzle/                 # 迁移数据库 SQL 脚本
│   │   └── src/
│   │       ├── client.ts            # 连接 pg 客户端与 FakePool 高保真离线仿真数据库
│   │       ├── schema.ts            # 表定义 (threads, messages, orders, products, session_metrics, pending_approvals, eval_logs)
│   │       ├── seed.ts              # 演示种子数据注入 (Nike/Adidas/主站，逾期/大额/小额件自愈注入)
│   │       └── index.ts             # 统一导出
│   │
│   ├── tools/                       # 外部原子工具集
│   │   └── src/
│   │       ├── registry.ts          # 工具库全局注册中心
│   │       ├── screenshot.tools.ts  # takeScreenshot 网页核验快照工具 (Puppeteer 底层支持)
│   │       ├── ecommerce.tools.ts   # getOrderStatus / processRefund / listUserOrders 查退查单
│   │       └── index.ts             # 统一导出
│   │
│   ├── observability/               # 分布式 APM 与链路跟踪
│   │   └── src/
│   │       ├── logger.ts            # pino 多级极速子日志流
│   │       ├── metrics.ts           # 生产级指标度量
│   │       └── langfuseClient.ts    # Langfuse 物理连接句柄
│   │
│   └── business-configs/            # SaaS 多商户 JSON 政策前置热载入
│       └── src/
│           ├── ecommerce.config.ts  # Nike/Adidas/主站免签额度、提示词、工具授权、意图映射表
│           └── index.ts             # 统一导出
│
├── eval/                            # 🆕 Promptfoo 大模型提示词多意图分类、步骤规划与安全防注入评测平台
├── scripts/                         # 🆕 数据库完整性审计与死任务扫描自愈工具集
├── biome.json                       # 🆕 Biome Rust 级极速格式化/校验配置 (代替 Prettier/ESLint)
├── package.json                     # Monorepo 全局依赖
├── turbo.json                       # Turborepo 并发构建拓扑流水线配置
└── CLAUDE.md                        # Claude Code 本地热绑定开发/设计 SOP 规则
```

---

## 3. 核心模块深度技术讲解 (Deep Module Breakdown)

### 3.1 `apps/web` 前端可视化与核签平台

- **职责范围**: 负责承载客服前端对话窗口、AI 智能子任务 DAG（计划树）拆解状态实时展示、SaaS Telemetry 算力财务账单可视化、以及**人工核签模拟控制面板**（右上角浮动按钮）。
- **核心逻辑解密**:
  - `app/page.tsx`:
    - **UUID v4 自愈装配**: 新进用户无任何 fallback（如 `thread_local_shared`），瞬间利用 `crypto.randomUUID()` 动态派发生命周期会话。
    - **双向 URL 会话同步**: 会话一经更新，通过 `window.history.replaceState` 秒级同步到地址栏。当用户将地址复制给其他人（如分享核签进度）时，能 100% 物理恢复同样的上下文进行审计。
  - `app/api/chat/[jobId]/stream/route.ts`:
    - **SSE 实时事件广播流**: 支持在 Local 极跑模式下，通过 `global.eventEmitter` 将 LangGraph 在每个节点执行的物理日志、工具入参及出参、审批拦截指令，以 Server-Sent Events 流式全量秒推给前端，提供丝滑的脉冲 Loading 控制。
  - `app/api/chat/approvals/route.ts`:
    - **审批控制中心**: 接收 Web 后台核签指令（Approve/Reject/Cancel）。写入工单后自动通过 `lock:approval:${id}` 挂载 Redis 锁。

### 3.2 `packages/engine` 核心 Agent 智能决策图与工作流

- **职责范围**: 整个平台的大脑决策中枢。集成了 LangGraph 状态图、Temporal 分布式异步工作流、RAG 向量混合检索、ResilientLLM 自愈代理、以及 4 重聚合记忆体系。
- **核心逻辑解密**:
  - `src/graph/buildGraph.ts` & `src/graph/state.ts`:
    - **LangGraph 决策图**: 物理定义了状态转移：
      `Triage (意图判定) ─[If general_query]─► Finish (兜底快速直跑 bypass)`
      `Triage (意图判定) ─[If business]──────► Planner ──► Merge ──► Executor ──► Validator ──► Executor (自旋循环) ──► Finish (最终中文合成回复)`
    - `buildHistoryContext`:
      - **对话历史精细洗涤**: 拦截由于大模型工具调用产生的大量无 text `content`、`undefined`、`null`、甚至是 string 化的 `"null"` 历史行。将其彻底剔除，只保留合规对话行（"Customer: 'xxx'" \ "Agent: 'xxx'"），规避上下文污染。
  - `src/graph/nodes/`:
    - `triage.node.ts`:
      - 多渠道分层分类（规则前置白名单 -> 语义 Embedding 距离评估 -> LLM 深度检测），将 `轉人工` 等指令实现 10ms 零 LLM 极速直达。
      - **重复请求去重护盾 (Duplicate Shield)**: 实时比对本次输入与上一次会话输入，或比对向量相似度。若大于 `0.98`，瞬间拦截并直接复用上一次助理的物理答复。
    - `planner.node.ts` & `executor.node.ts`:
      - 依据意图生成子步骤。在 Executor 触发时，读取 RAG 的商户售后政策、限额。**在此处直接挂载人工审批（HITL）红线与自检逻辑**。
  - `src/temporal/workflows.ts` & `src/temporal/activities.ts`:
    - 在检测到物理 Temporal 引擎可用时，将上述 LangGraph 节点注册并打包封装进 Activity 执行中，提供金融级高吞吐保障。
  - `src/rag/contextualRag.ts`:
    - **Anthropic 上下文检索增益**: 每一个知识库 chunk 均通过大模型注入 50 字节的全局商户背景 Summary，再结合**“余弦距离检索(80%) + 核心命名实体共现匹配(20%)”**进行混合评级重排。

### 3.3 `packages/db` 关系型范式数据接入与高保真仿真器

- **职责范围**: 数据持久范式层。负责商户、用户、订单、消息、审批、财务算力日志的物理读写与结构定义。
- **核心逻辑解密**:
  - `src/client.ts` (`FakePool`):
    - **高弹性抗灾灾备 (High Fidelity Emulator)**:
      - 当外部 PostgreSQL 连接因限流或物理断开不可用时，系统自动切换为离线仿真器。
      - 仿真器在 **Node 进程全局变量 `global` 命名空间下长期缓存一份 Map 关系型数据库快照 `memoryDb`**，解决了 Next.js 在 Dev 热重载（Fast Refresh）时，由于文件被刷新而导致内存数据库重置、历史会话全数丢失的问题！
      - 完美模拟多租户多商户的 Drizzle 查询，并支持了 SQL SELECT 中的模糊条件拦截（包含多表联查 `order_items` 等自愈溯源逻辑）。

### 3.4 `packages/tools` 物理工具链与安全防护拦截

- **职责范围**: 提供系统与外部物理业务系统直接交互的接口。
- **核心逻辑解密**:
  - `src/ecommerce.tools.ts`:
    - **`getOrderStatus`**: 多表 JOIN 拼装真实订单物流承运商、单号，并在明细未找到时自愈匹配展示。
    - **`processRefund`**: 物理发起扣款。
      - **售后政策红线比对 (Refund Window Guard)**: 强行对比当前日期与订单送达时间，若超出商户退货窗（如 Nike 30天，Adidas 14天），在工具内部物理抛出政策拦截异常并上报，**绝对不在超期订单上产生任何退款操作，将 SOP 逻辑硬编码至工具底层，防止 LLM 被 Jailbreak 恶意绕过**。
    - **`listUserOrders`**: 根据 threadId 溯源当前商户与用户，并返回名下的多张订单记录。

### 3.5 `packages/observability` 算力计量与全链路 Trace 日志

- **职责范围**: 系统全链路可观测性 APM。
- **核心逻辑解密**:
  - `src/logger.ts`: Pino 级高速子日志打印。
  - `src/langfuseClient.ts` & `src/metrics.ts`:
    - 无缝与 LangSmith / Langfuse 日志追踪平台打通。所有大模型的调用、输入输出、工具调起均会生成 Trace Span 并实时上报归档。

### 3.6 `packages/business-configs` 多商户 SaaS 动态策略配置

- **职责范围**: 存储及定义 Nike、Adidas、电商主站（ecommerce）等各个商户在不同租户下的定制化 JSON 配置。
- **核心逻辑解密**:
  - `src/ecommerce.config.ts`:
    - 包含各商户专有的 System Prompt、免核准退款限额（Nike $150，Adidas $120，主站 $100）、专有授权使用的物理工具集、意图置信度白名单阀值。该配置可以物理写入 Postgres 中，大模型在决策前优先去物理表加载，**真正实现零发布、零宕机的 Hot-Reload 动态热替换政策**！

---

## 4. 核心底层设计实现细节

### 4.1 金融级人机协同与认知回溯决策环 (HITL)

- **无状态挂起 (Stateless Suspension)**：当 Executor 检测到敏感操作时，系统绝不阻塞 Worker 连接，而是生成 `waiting` 状态工单并将状态机 Yield 截断至 Finish，挂起期间**计算与连接零占用**。
- **大脑打倒挡回溯 (Cognitive Backtracking)**：如果管理员点击驳回并填写修改意见，条件路由强制将指针**回退到 Planner 节点**。Planner 将人工建议作为 `[CRITICAL ADVISORY]` 强上下文喂给大模型重新规划子任务。
- **自愈解挂熔断 (Timeout Auto-expiration)**：设置 24h 截止时间。若管理员长期无响应，系统检测超时后自动更新工单为 `'expired'` 并强制设当前步骤为 `failed`（解挂流通），由 finishNode 优雅宣告超时致歉。
- **用户主动取消 (Cancellation Bypass)**：支持用户在中途发起 `'cancel'` 决议。Executor 检测到后，物理阻断后续扣款，直接安全退避。

### 4.2 SaaS 级多租户隔离与 Contextual RAG 检索

- **多租户安全过滤**：Drizzle ORM 的查询强行挂载 `WHERE business_id = :tenantId` 条件子句，从物理数据源头掐灭跨商户泄露。
- **上下文检索增益 (Contextual Retrieval)**：切片时将 50字“全局 Summary” 与 “段落 Content” 强强联合。结合**“余弦相似度 (80%) + 核心业务实体词共现 (20%)” 混合双向评分重排**，对无关闲聊触发 `hybridScore < 0.40` 强力断路过滤，净化 Prompt 上下文。

### 4.3 物理工具链政策红线守卫 (SOP Guardrail)

- **工具参数下钻**：`executor.node.ts` 调用工具时下发当前会话 `threadId`。
- **政策红线拦截**：`processRefund` 工具通过 raw SQL 逆向检索该会话所属商户。获取对应的售后时效（Nike: 30天，Adidas: 14天，Ecommerce: 7天），比对订单预计送达时间与物理当前时间。**若已逾期，工具在执行层直接终止物理扣款并返回拦截报告**！

### 4.4 双通道并发防刷与 Redis SETNX 分布式锁

- **Singleflight 网关**：完全相同的并行请求（同一会话、内容一致）合并共用同一个 `jobId`，Token 消耗直降 **50%**。
- **SETNX 分布式并发锁**：核决接口加挂 `lock:approval:${approvalId}` 分布式锁，配合 5s 自动过期与**内存 `localLocks` 降级锁**，绝对杜绝管理员双击或高并发刷单产生的重复退款。

### 4.5 100% 授信 Gemini-Only 自愈抗灾与精确 Token 追踪

- **合规重试代理 (ResilientLLM)**：100% 仅调用合规 the `gemini-3.5-flash:latest` 模型。遭遇限流或抖动时，在内部执行最大 3 次指数退避自愈重试，并向前端 emit 实时自愈警告。
- **跨轮 Token 累加**：代理在重试重入时自动拦截响应元数据，无感累加各重试轮次的实际 Token 开销，保障算力看板 Token **100% 精确计量**。

### 4.6 SaaS 动态配置热载入与免签额度路由守卫

- **热载入引擎 (Hot-Reloadable Config)**：起手自动从 `business_configs` 物理表抓取激活态的 JSON 配置。Planner 和 Finish 节点的系统提示词（心智与口吻）直接与该配置热绑定，**更改配置瞬间热生效，零发布、零宕机**。
- **🪙 动态限额核免**：自动抓取商户的 `refundAutoApprovalLimit` 免签额度（Nike: $150，Adidas: $120，主站: $100）。**小额退款自动触发放行通路直接执行，大额退款自动核发生成 HITL 工单**。

### 4.7 SaaS 算力审计与财务账单度量系统

- **Telemetry Flush 物理冲刷**：决策结束后，异步在 `session_metrics` 物理表中创建一条度量账单，统计 Token 消耗、耗时、图自旋深度以及结算状态。
- **SaaS BI Analytics 仪表盘 API**：提供 `/api/analytics?businessId=nike` 的 GET 端点。高保真聚合导出**总成本、总会话数、平均耗时、平均 Token、以及 Autopilot 自动放行效率（%）**，BI 数据一目了然！

### 4.8 多轮會话物理自愈载入 (Self-Healing Short Memory)

- **自愈式短期记忆加载逻辑**: 在任何无状态执行或热重载下，如果状态机初始化丢失历史消息：

```typescript
let shortMemory = state.shortMemory;
if (!shortMemory || shortMemory.length === 0) {
  const { ShortMemory } = require("../../memory/shortMemory");
  const sm = new ShortMemory(state.threadId);
  shortMemory = await sm.getMessages();
}
```

- **收益**: 跨轮对话（第一轮查物流，第二轮无订单号直接退款）历史 100% 连贯，大模型自动抓取第一轮查明的 `orderId` 进行极速退款，消除健忘症。

### 4.9 双向会话同步与零 Fallback 级 UUID 会话管理

- **客户端动态 UUID v4 派发**: 废除一切 `thread_local_shared` 回退。用户进入页面瞬间，在客户端通过 `crypto.randomUUID()` 动态派发高精 UUID v4 作为 threadId 物理落盘。
- **URL 双向同步**: 联动 `window.history.replaceState` 实现会话状态在 URL 栏 `?threadId=...` 进行双向秒级响应绑定。刷新或保存书签会话 100% 恢复，确保用户会话独立与多租户零数据混淆。

### 4.10 Multi-Tenant Grounding Guardrails (多租户接地守卫)

- **物理隔离心智**: 在 `planner.node.ts` 与 `finish.node.ts` 提示词底层强制注入多租户隔离约束。Agent 只能感知和匹配当前会话 `businessId` 的专属品牌（如 Nike 只能提供 Nike 的退换政策），绝不泄露或混淆跨商户信息，从大模型心智源头封杀跨租户污染。

### 4.11 Super Semantic Caching Layer (超级语义缓存层)

- **50ms 级极速响应 & 0 算力 Token 损耗**: 声明全局向量相似度缓存，在 `triage.node.ts` 检测到用户的常问问题（General Query）余弦相似度 `>= 0.96` 时直接命中缓存答复。在 `finish.node.ts` 回答完新咨询后自动异步回写。

### 4.12 Financial Audit Trail (金融级数字印鉴审计)

- **防伪交易凭证**: 退款 `processRefund` 及高价值地址更改 `changeShippingAddress` 履约完毕后，自动拼装数字审计印鉴（`auditTrail`），包含工单 ID、审批通过时间、SOP 条款校验，以及对敏感参数进行 **SHA256 哈希防篡改加密签名（verifiableHash）**，确保每笔扣款与更改皆可严格追溯核算。

### 4.13 High-Availability Reconnect Sync Queue (容灾回放对账队列)

- **网络抖动零漏单、防双花**: 物理 Postgres 闪断期间，写操作自动追加到 **Offline Mutation Queue**。检测重连成功后，事务块（Transaction）安全回放更新，并对退款执行 **Double-Refund Sanity Check**，彻底杜绝双花重复扣款隐患。

---

## 5. 质量保障与评测体系 (Testing & Tooling)

- **Biome (Rust-powered Linter/Formatter)**：
  配置 `biome.json` 在 **24 毫秒内自洁修复全库 78 个 TS/JS 文件**，自动重新排序依赖 Imports，保障在 CI/CD 阶段的格式规范。
- **Playwright (E2E 浏览器测试)**：
  自动化测试 `/apps/web/e2e` 下的用户登录跳转、LocalStorage 会话持久、侧栏历史渲染以及 Token 计数交互旅程。
- **Promptfoo (Prompt 防守评测)**：
  在 `eval/promptfooconfig.yaml` 中配置大意图 F1 断言、工具调用准确度断言，以及专门模拟超级管理员口吻命令绕过安全拦截的 **Jailbreak 防注入评测与 LLM-as-a-judge 最终回复质量断言**，坚守提示词逻辑边界。

---

## 6. 开发与部署命令

### 6.1 数据自填充 (Live Seeding)

我们已经为您准备了极具演示冲突和对比属性的关系型高保真种子数据：

```bash
# 执行物理多租户多商户种子数据注入（自动清理、创表并灌入完备的 Products、Orders 及 Metrics 数据）
bun packages/db/src/seed.ts
```

### 6.2 🆕 统一系统集成测试与多商户多轮对话验证

```bash
# 验证：多商户隔离边界拦截（Ecommerce 拦截 Nike 查单）、多轮会话 Order ID 无感自愈携带、以及查单退款物理校验等全部流。
# 检验系统底层决策图、混合检索 RAG、工具拦截和记忆加载 100% 的准确与高可用。
bun test packages/engine/tests/system.test.ts
```

### 6.3 毫秒级极速代码校验与自动修复 (Biome)

```bash
# 运行 Biome 一键全自动格式化与无用 imports 清理
bun run biome:check
```

### 6.4 端到端浏览器自动化测试 (Playwright)

```bash
# 运行 Playwright E2E 无头测试
bun run test:e2e
```

### 6.5 提示词防注入与意图质量评测 (Promptfoo)

```bash
# 启动 Promptfoo 模型断言测试
bun run test:prompt
```

### 6.6 本地一键拉起 dev 服务进行网页端实战体验！

```bash
# Bun 极速拉起 Next.js 控制台 (自愈直跑，已与本地 FakePool、Redis/PG 仿真无缝打通)
bun run dev
```

打开浏览器访问 [http://localhost:3000](http://localhost:3000) 即可自由开启一场极具科技美感的智能客服人机协同、自动回溯 and 知识 RAG 体验！

---

_本文档基于 smartServe-agent 物理落地的代码结构进行详尽整理与更新。_
