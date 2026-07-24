# Distributed Intelligent Customer Support Agent Platform

基于 **Turborepo + Bun Workspaces** 统一管理的分布式智能客服 Agent 中台。系统采用 **LangGraph (StateGraph)** 决策图进行核心业务决策编排，并原生支持 **Temporal 工作流引擎** 和 **本地极速直盘模拟器** 双模切换。

平台通过高保真离线沙箱、多层意图识别管道、四维记忆系统、分布式二级缓存以及本地物理浏览器截图等硬核技术，实现了一个真正能“落地、抗压、物理流转”的客服业务闭环。

---

## 目录

1. [项目架构与双模引擎设计](#1-项目架构与双模引擎设计)
2. [工作空间目录结构](#2-工作空间目录结构)
3. [核心技术实现细节](#3-核心技术实现细节)
   - [3.1 多级分层意图识别管道](#31-多级分层意图识别管道)
   - [3.2 四维高保真记忆系统](#32-四维高保真记忆系统)
   - [3.3 物理工具链集成与二级缓存](#33-物理工具链集成与二级缓存)
   - [3.4 高保真离线无缝降级设计](#34-高保真离线无缝降级设计)
4. [技术选型](#4-技术选型)
5. [开发与部署命令](#5-开发与部署命令)
6. [极致性能与成本优化设计](#6-极致性能与成本优化设计)

---

## 1. 项目架构与双模引擎设计

平台采用 **双模弹性引擎** 设计，在保障开发体验的同时，具备工业级的抗压与灾备恢复能力：

```
┌─────────────────────────────────┐
│     Next.js Web (apps/web)      │ ← 前端UI + 轻量级API，负责会话管理、历史拉取、SSE流式呈现
└────────────────┬────────────────┘
                 │
        POST /api/chat 提交
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
│   finish(终点合成回复，拒绝幻觉，依据真实物理表数据提炼答复)                 │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        数据持久化与二级缓存层                         │
│  - PostgreSQL / Drizzle ORM (含 FakePool 离线物理内存表仿真)            │
│  - Redis 物理分布式缓存 (含 Local Map Cache 异常降级机制)              │
└────────────────────────────────────────────────────────────────────────┘
```

1. **本地极速直跑模式 (LangGraph StateGraph Direct Mode)**：当 Temporal 离线时，Next.js 会自动将任务路由给本地直跑引擎。通过全局的运行态 Promise 进行跟踪，并使用自定义的 `AgentEventEmitter` 物理播放与订阅日志。
2. **生产级工作流模式 (Temporal Workflow Mode)**：当 7239 端口探针物理连接成功，自动激活 Temporal 状态机，将节点作为 Activity 逐级驱动。支持注册 `currentStatusQuery`、`currentPlanQuery`、`chatHistoryQuery` 供外部对中间状态进行细粒度审计。

---

## 2. 工作空间目录结构

本项目基于 **Bun Workspaces** 管理的多包单体仓库 (Monorepo)：

```
.
├── apps/
│   └── web/                         # Next.js 15 控制台应用 (App Router)
│       ├── app/
│       │   ├── api/
│       │   │   ├── auth/login/      # 用户物理邮箱注册与登录，自动初始化会话
│       │   │   ├── chat/            # 提交聊天任务 (判定 Temporal 并路由分流)
│       │   │   ├── chat/[jobId]/stream/ # SSE 双通道实时状态与结果广播
│       │   │   ├── chat/messages/   # 拉取 PostgreSQL 物理消息历史
│       │   │   └── chat/threads/    # 创建与获取用户会话列表
│       │   ├── login/               # 独立登录路由页面 (LocalStorage 持久化 Session)
│       │   ├── page.tsx             # 主控制台，含有向有环图状态实时监控面板、快照查看器
│       │   └── layout.tsx
│       └── components/ui/           # 基于 shadcn/ui + Tailwind CSS v4 的高档暗黑风组件
│
└── packages/
    ├── engine/                      # 核心 Agent 决策图与引擎
    │   └── src/
    │       ├── graph/
    │       │   ├── nodes/           # Triage, Planner, Executor, Validator, Merge, Finish 节点
    │       │   ├── state.ts         # LangGraph 强类型 Annotation 状态定义
    │       │   ├── buildGraph.ts    # 编译 StateGraph、毫秒级欢迎语极速通路实现
    │       │   └── eventEmitter.ts  # EventEmitter 分发器，带 150ms 物理延迟播放，彻底解决加载卡死 Bug
    │       ├── memory/              # 四维记忆管理类 (Short, Long, Task, Episodic Memory)
    │       ├── llm/                 # 统一 Gemini-3.5-Flash 与 Embedding 初始化调用层
    │       └── temporal/            # Temporal 统一 Worker、Client 探针检测与 Workflow 核心逻辑
    │
    ├── db/                          # 数据接入层
    │   └── src/
    │       ├── schema.ts            # Drizzle ORM 表结构定义 (事实库、事件流、意图日志、审批、LLM调用)
    │       └── client.ts            # 数据库连接，提供 FakePool 高保真内存表仿真降级
    │
    ├── tools/                       # 物理工具链
    │   └── src/
    │       ├── registry.ts          # 工具集中注册与调用中心
    │       ├── ecommerce.tools.ts   # 包含 getOrderStatus (Redis 二级缓存) 和 processRefund (强一致性缓存清除)
    │       └── screenshot.tools.ts  # takeScreenshot 看板截图，Puppeteer-core 直接调起本地 Chrome 并落盘
    │
    ├── business-configs/            # 业务多配置管理层 (统一管理 SystemPrompt, 意图集及阈值)
    │   └── src/
    │       └── ecommerce.config.ts  # 电商配置快照
    │
    └── observability/               # 可观测性
        └── src/
            ├── logger.ts            # Pino 日志封装，支持 Serverless 友好型 Stdout 兜底
            └── langfuseClient.ts    # 物理 Mock trace
```

---

## 3. 核心技术实现细节

### 3.1 多级分层意图识别管道

系统在 `triageNode` 中实现了一个多级防御型的意图识别管道，防止用户输入直接穿透到大模型造成高昂的 Token 费用和高延迟：

1. **Step 0: 格式与符号预拦截**：
   - 空消息快速过滤。
   - 纯符号、大量特殊标点直接用预设欢迎词在毫秒级旁路返回。
   - 大于 1000 字符的垃圾灌水文本自动拦截，并生成人性化提示。
2. **第一重防护：语义防抖与重复提问拦截盾 (Duplicate Question Shield)**：
   - 历史消息比对。若当前提问与上一轮用户提问文本完全一致，或通过 `text-embedding-005` 提取的向量余弦相似度达到 **$\ge 0.98$**，系统将触发拦截。
   - 绕过大模型与工具链自旋，在 $10\text{ms}$ 内直接复用并包裹历史答复输出，极大提升网络抖动下的响应速度。
3. **Step 1: 规则白名单 (Quick Whitelist)**：
   - 问候欢迎语（“你好”、“Hi”等）直达欢迎页面。
   - 退出会话词自动触发 politely 退出流程。
   - 转人工指令（如“转人工客服”）瞬间调起虚拟物理人工队列分配逻辑。
4. **Step 2: Embedding 语义向量相似度预分类**：
   - 系统将输入与预设的 `order_status`、`refund` 和 `out_of_scope`（超出范围）錨点句组进行余弦相似度计算。
   - 订单/退款相似度 **$\ge 0.88$** 且与超出范围词有显著边距（$\ge 0.08$）时，系统直接识别意图进入下一步，**节省 $1.5$ 秒以上的大模型推理时间**。
   - 超出范围分值 **$\ge 0.86$** 时，直接触发安全拦截，委婉拒绝解答，杜绝非法/高危输入破坏业务边界。
5. **Step 3: LLM 深度分流 (Gemini 3.5 Flash)**：
   - 若前置层无法做出高置信度裁决，则降级至 `Gemini 3.5 Flash` 大模型。通过严格的 Prompt 规约输出标准化 JSON 数组，解析后驱动后续拓扑图流转。

### 3.2 四维高保真记忆系统

通过 `packages/engine/src/memory/` 实现了四种不同维度的记忆，全方位刻画用户画像：

| 记忆类型 | 数据实体 | 获取与提取技术 | 业务目的 |
|---|---|---|---|
| **Short Memory (会话记忆)** | `messages` 表 | 读取 Drizzle PostgreSQL 物理记录，按时间排序。 | 维持单次 Thread 会话的历史语境。 |
| **Long Memory (事实偏好)** | `long_memory_facts` 表 | 提取对话文本，通过 `text-embedding-005` 嵌入入库。搜索时按**相似度阈值 $\ge 0.65$** 进行内存余弦过滤，**限定 Top 5 最优偏好**。 | 跨会话记住用户特定事实、操作偏好及规则指令。 |
| **Episodic Memory (事件记忆)** | `episodic_events` 表 | 物理存入带重要性评分 (1-10) 的跨会话事件。搜索时过滤**相似度 $\ge 0.60$**，**限制 Top 3 极简呈现**。 | 追踪具体的重大事件、履约成功记录及异常处理轨迹。 |
| **Task Memory (进度记忆)** | `task_memory` 表 | 在决策图中流转并持久化序列化 TaskPlan。 | 保持和跟踪有向有环图每一步的子步骤执行进度状态。 |

### 3.3 物理工具链集成与二级缓存

工具链集成在 `packages/tools/` 目录中，强调“真实物理执行”与“强缓存一致性”：

*   **`getOrderStatus` (订单物流状态查询)**：
    *   **分布式二级缓存**：优先物理连接 Redis，读取 `cache:order_status:<orderId>`，TTL 设为 **$60$ 秒**；若 Redis 连接超时或离线，系统无缝且静默降级为本地内存 Map 缓存。
    *   两层缓存均不命中时，才会去物理数据库拉取。
*   **`processRefund` (快捷退款办理)**：
    *   **缓存强一致性**：退款接口会直接物理更新 PostgreSQL 里的订单表状态为 `'refunded'`。
    *   **主动缓存作废**：操作成功后，立即主动且全渠道清除 Redis 及本地 Map 中关于此订单的物流缓存 key，彻底解决由于缓存未同步导致用户退款后查询订单状态仍为“已发货”的业务致命一致性 Bug！
*   **`takeScreenshot` (系统看板界面截图核验)**：
    *   使用 `puppeteer-core` 自动检测并调起本地电脑上安装的物理 Chrome 浏览器。
    *   在 headless 模式下高保真渲染目标 URL。
    *   **突破超长数据流设计**：截图直接以 PNG 物理文件形式写入 `apps/web/public/screenshots/` 文件夹中。接口仅向外分发并返回 Next.js 静态文件相对相对路径（如 `/screenshots/screenshot_xxx.png`）。
    *   **彻底告别传统超长 Base64 字符串**，防止 SSE 数据传输通道网络卡顿，并保护 Temporal 运行详情 UI 绝不因为大流渲染而死机崩溃。

### 3.4 高保真离线无缝降级设计

作为一套能够在任何没有网络的开发环境下随时运行的高保真系统，平台内置了极其丰富的降级方案：

*   **Drizzle ORM 的 FakePool 仿真**：
    *   当环境变量未提供 `DATABASE_URL` 时，系统绝不报错，而是秒级激活一个 **高保真内存物理仿真数据库** `FakePool`。
    *   `FakePool` 内部通过一套强大的 SQL 语法硬解析引擎，支持解析和模拟 `CREATE TABLE`、`INSERT INTO MESSAGES`、`SELECT FROM ORDERS`、`UPDATE`、`getUserThreads` 以及用户注册、会话建立等全部物理行为！保证左侧会话历史、刷新恢复均能 100% 动态呈现。
*   **Redis 的 Local Map 降级**：
    *   Redis 初始化中内置 1.5 秒的极速探针超时，遇网络阻断自动转为内存级 Local Map 缓存，保护业务接口可用性。
*   **可观测性降级**：
    *   Pino 捕获 Next.js 在预渲染 (SSR) 和 Bundled 模式下由于 Webpack 隔离导致的 Pino-pretty 缺失异常，无缝降级为简洁的 Stdout 标准输出，保证 Next.js 构建绝不中断。
    *   Langfuse 初始化直接封装为高保真 Mock 对象，防止无凭证下启动崩溃。

---

## 4. 技术选型

| 维度 | 库 / 工具 | 主要用途 | 选型优势 |
|---|---|---|---|
| **包管理 / 构建** | `Turborepo` + `Bun` | Monorepo 多包协调、极速执行、代码共享 | 告别多进程 node\_modules 冲突，依赖关系极简。 |
| **前端应用框架** | `Next.js 15` (App Router) | Web 实时控制台、SSE 状态流分发 | 原生 Server-Sent Events 支持，流式播放体验流畅。 |
| **Agent 编排** | `@langchain/langgraph` | 基于 StateGraph 的有向有环图状态流转 | Checkpoint 控制，多分支条件路由。 |
| **分布式中台** | `@temporalio/client` / `worker` | 长任务编排、重试与 Activity 分布式托管 | 支持分钟级、小时级超长高风阻任务的精细容错。 |
| **大语言模型** | `gemini-3.5-flash:latest` | Triage, Planner, Finish 答复生成 | 极高的吞吐额度与性价比，毫秒级流式响应。 |
| **数据库 ORM** | `drizzle-orm` + `pg` | 数据持久化、实体建模、仿真模拟 | 配合 `FakePool` 完美实现无缝离线开发。 |
| **外部截图工具** | `puppeteer-core` | 渲染真实网页并保存快照 | 自适应 Darwin / Win32 / Linux Chrome 物理路径。 |
| **日志与结构日志** | `pino` | 结构化生产级日志 | 带有 SSR / Serverless 打包环境的防护。 |

---

## 5. 开发与部署命令

### 5.1 本地快速开发 (Offline / 离线直跑)

项目完全支持**无依赖离线直跑**（不需要开启 Postgres、Redis 或 Temporal）：

```bash
# 安装全部工作空间依赖 (使用 Bun 极速安装)
bun install

# 启动 Next.js 前端控制台 (默认直跑内存仿真数据库，无数据库依赖！)
bun run dev
```
打开浏览器访问 [http://localhost:3000](http://localhost:3000) 即可使用。您可以任意在输入框内注册邮箱，开启并体验多轮对话。

### 5.2 数据库 Schema 变更

在有真实 PostgreSQL 环境下：

```bash
# 生成 Drizzle Migrations
bun drizzle-kit generate

# 将 Drizzle Schema 物理推送到 Postgres 数据库
bun drizzle-kit push
```

### 5.3 启动 Temporal 分布式任务引擎

如果您需要启动物理 Temporal 工作流编排：

```bash
# 启动本地 Temporal 服务 (默认端口 7233/7239 物理映射)
# 本地需运行 docker-compose.yml 容器
docker-compose up -d

# 启动引擎端 Temporal Worker (负责具体 Activities 的物理调度消费)
bun --filter engine worker
```

---

## 6. 极致性能与成本优化设计

平台不仅关注技术架构的完整性，而且在物理执行效率、大模型调用费用上进行了极致的优化：

1. **Quick Greeting Bypass (10毫秒直达问候通道)**：
   - 传统客服 Agent 最忌讳用户发一句“你好”、“哈喽”也要经过耗时 2-3 秒的 LLM、RAG、Tools 分类，既消耗 Token 又延迟巨大。
   - 平台在 `runAgent` 入口处建立快速判定白名单。若用户发送标准问候词，不经过任何 LangGraph 节点和 RAG，**直接在 $10\text{ms}$ 内秒级返回精美的中文指引答复**，同时完成物理消息建档，体验快如闪电！
2. **Short Input Optimization (短文本向量跳过机制)**：
   - 如果用户输入字数 $\le 3$ 字符，系统判定此输入毫无检索长期记忆事实（Facts）或跨会话事件（Events）的必要。
   - **直接避开耗时的 Embedding 向量化调用**，彻底省下 1 秒钟的网络请求和 OpenAI 向量库计费！
3. **Validator pedantic NO Guard (核验绿灯哨兵)**：
   - `Validator` 节点由 LLM 判断工具结果是否满意。但大模型容易对非工具执行步骤（如提炼信息、网页截图、告知用户等）表现出过于苛刻的幻觉判决，从而频繁将状态重置或死循环。
   - 平台通过检索步骤描述（检测包含 `inform`/`communicate`/`tell`/`screenshot` 等关键词），凡属于信息反馈或看板截图类的子任务且无物理报错，**核验器无条件放行绿灯通关**，避免系统自旋死循环。

---

*本文档基于项目当前物理已落地的代码结构进行详尽整理与更新。*
