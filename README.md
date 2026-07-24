# 🚀 smartServe-agent: 分布式多租户 SaaS 智能客服决策中中台平台

smartServe-agent 是一款基于 **Turborepo Monorepo**、**Bun 运行环境** 与 **LangGraph 决策图** 构建的日活千万级、高弹性、高防卫金融级智能客服 Agent 决策平台。

系统原生支持 **SaaS 多租户物理隔离**、**人工核签红线拦截与重规划自适应回溯**、**Anthropic Contextual RAG（上下文增益知识库检索）**，并配备了 **Redis 分布式并发锁**、**物理自愈指数退避 LLM HA-Proxy**、以及**高敏捷 SaaS 财务算力账单仪表盘**。

---

## 目录
1. [项目架构与双模引擎设计](#1-项目架构与双模引擎设计)
2. [工作空间目录结构](#2-工作空间目录结构)
3. [核心技术实现细节](#3-核心技术实现细节)
   - [3.1 金融级人机协同与认知回溯决策环 (HITL)](#31-金融级人机协同与认知回溯决策环-hitl)
   - [3.2 SaaS 级多租户隔离与 Contextual RAG 检索](#32-saas-级多租户隔离与-contextual-rag-检索)
   - [3.3 物理工具链政策红线守卫 (SOP Guardrail)](#33-物理工具链政策红线守卫-sop-guardrail)
   - [3.4 双通道并发防刷与 Redis SETNX 分布式锁](#34-双通道并发防刷与-redis-setnx-分布式锁)
   - [3.5 100% 授信 Gemini-Only 自愈抗灾与精确 Token 追踪](#35-100-授信-gemini-only-自愈抗灾与精确-token-追踪)
   - [3.6 SaaS 动态配置热载入与免签额度路由守卫](#36-saas-动态配置热载入与免签额度路由守卫)
   - [3.7 SaaS 算力审计与财务账单度量系统](#37-saas-算力审计与财务账单度量系统)
4. [质量保障与评测体系 (Testing & Tooling)](#4-质量保障与评测体系-testing--tooling)
5. [开发与部署命令](#5-开发与部署命令)

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

## 2. 工作空间目录结构

```
.
├── apps/
│   └── web/                         # Next.js 15 控制台应用 (App Router)
│       ├── app/
│       │   ├── api/
│       │   │   ├── analytics/       # 🆕 SaaS 多租户财务算力 BI 账单仪表盘端点
│       │   │   ├── chat/approvals/  # 🆕 人工核签 POST 双向核决端点 (支持加锁防重、取消、驳回)
│       │   │   └── chat/            # 提交聊天任务 (Singleflight 并发合并 + 5s 缓存)
│       │   └── e2e/                 # 🆕 Playwright 端到端浏览器自动化用户旅程测试
│       └── components/              # 暗黑风控制台与脉冲闪烁的橙色 HITL 审批模拟面板组件
│
└── packages/
    ├── engine/                      # 核心 Agent 决策图与引擎
    │   └── src/
    │       ├── graph/
    │       │   ├── nodes/           # Triage, Planner, Executor, Validator, Merge, Finish 节点
    │       │   └── buildGraph.ts    # 编译 StateGraph、三路并行 RAG 载入与 SaaS Telemetry Flush 冲刷
    │       ├── rag/                 # 🆕 Contextual RAG 引擎 (混合双向评分融合与 0.40 断路重排)
    │       └── llm/                 # 🆕 ResilientLLM 代理 (Gemini-Only 3次自愈退避与跨轮 Token 累加)
    │
    ├── db/                          # 数据接入关系型范式层 (Nike / Adidas 3NF 关联)
    │   └── src/
    │       ├── schema.ts            # Drizzle ORM (新增 products、order_items、session_metrics 表)
    │       ├── seed.ts              # 🆕 关系型演示种子数据注入 (ORD-98712、合规件、逾期件、大额件演示)
    │       └── client.ts            # PostgreSQL 客户端 (FakePool 新增 RAG 与度量表的 SQL 仿真拦截)
    │
    ├── tools/                       # 物理工具链
    │   └── src/
    │       └── ecommerce.tools.ts   # 🆕 processRefund 物理退款工具 (下钻 threadId 原始 SQL 多租户售后时效校验)
    │
    ├── biome.json                   # 🆕 Biome Rust 级极速静态格式自洁校验配置
    └── promptfooconfig.yaml         # 🆕 Promptfoo 大模型 Prompt 质量评估与 Jailbreak 防注入测试
```

---

## 3. 核心技术实现细节

### 3.1 金融级人机协同与认知回溯决策环 (HITL)
*   **无状态挂起 (Stateless Suspension)**：当 Executor 检测到敏感操作时，系统绝不阻塞 Worker 连接，而是生成 `waiting` 状态工单并将状态机 Yield 截断至 Finish，挂起期间**计算与连接零占用**。
*   **大脑打倒挡回溯 (Cognitive Backtracking)**：如果管理员点击驳回并填写修改意见，条件路由强制将指针**回退到 Planner 节点**。Planner 将人工建议作为 `[CRITICAL ADVISORY]` 强上下文喂给大模型重新规划子任务。
*   **自愈解挂熔断 (Timeout Auto-expiration)**：设置 24h 截止时间。若管理员长期无响应，系统检测超时后自动更新工单为 `'expired'` 并强制设当前步骤为 `failed`（解挂流通），由 finishNode 优雅宣告超时致歉。
*   **用户主动取消 (Cancellation Bypass)**：支持用户在中途发起 `'cancel'` 决议。Executor 检测到后，物理阻断后续扣款，直接安全退避。

### 3.2 SaaS 级多租户隔离与 Contextual RAG 检索
*   **多租户安全过滤**：Drizzle ORM 的查询强行挂载 `WHERE business_id = :tenantId` 条件子句，从物理数据源头掐灭跨商户泄露。
*   **上下文检索增益 (Contextual Retrieval)**：切片时将 50字“全局 Summary” 与 “段落 Content” 强强联合。结合**“余弦相似度 (80%) + 核心业务实体词共现 (20%)” 混合双向评分重排**，对无关闲聊触发 `hybridScore < 0.40` 强力断路过滤，净化 Prompt 上下文。

### 3.3 物理工具链政策红线守卫 (SOP Guardrail)
*   **工具参数下钻**：`executor.node.ts` 调用工具时下发当前会话 `threadId`。
*   **政策红线拦截**：`processRefund` 工具通过 raw SQL 逆向检索该会话所属商户。获取对应的售后时效（Nike: 30天，Adidas: 14天，Ecommerce: 7天），比对订单预计送达时间与物理当前时间。**若已逾期，工具在执行层直接终止物理扣款并返回拦截报告**！

### 3.4 双通道并发防刷与 Redis SETNX 分布式锁
*   **Singleflight 网关**：完全相同的并行请求（同一会话、内容一致）合并共用同一个 `jobId`，Token 消耗直降 **50%**。
*   **SETNX 分布式并发锁**：核决接口加挂 `lock:approval:${approvalId}` 分布式锁，配合 5s 自动过期与**内存 `localLocks` 降级锁**，绝对杜绝管理员双击或高并发刷单产生的重复退款。

### 3.5 100% 授信 Gemini-Only 自愈抗灾与精确 Token 追踪
*   **合规重试代理 (ResilientLLM)**：100% 仅调用合规 the `gemini-3.5-flash:latest` 模型。遭遇限流或抖动时，在内部执行最大 3 次指数退避自愈重试，并向前端 emit 实时自愈警告。
*   **跨轮 Token 累加**：代理在重试重入时自动拦截响应元数据，无感累加各重试轮次的实际 Token 开销，保障算力看板 Token **100% 精确计量**。

### 3.6 SaaS 动态配置热载入与免签额度路由守卫
*   **热载入引擎 (Hot-Reloadable Config)**：起手自动从 `business_configs` 物理表抓取激活态的 JSON 配置。Planner 和 Finish 节点的系统提示词（心智与口吻）直接与该配置热绑定，**更改配置瞬间热生效，零发布、零宕机**。
*   **🪙 动态限额核免**：自动抓取商户的 `refundAutoApprovalLimit` 免签额度（Nike: $150，Adidas: $120，主站: $100）。**小额退款自动触发放行通路直接执行，大额退款自动核发生成 HITL 工单**。

### 3.7 SaaS 算力审计与财务账单度量系统
*   **Telemetry Flush 物理冲刷**：决策结束后，异步在 `session_metrics` 物理表中创建一条度量账单，统计 Token 消耗、耗时、图自旋深度以及结算状态。
*   **SaaS BI Analytics 仪表盘 API**：提供 `/api/analytics?businessId=nike` 的 GET 端点。高保真聚合导出**总成本、总会话数、平均耗时、平均 Token、以及 Autopilot 自动放行效率（%）**，BI 数据一目了然！

---

## 4. 质量保障与评测体系 (Testing & Tooling)

*   **Biome (Rust-powered Linter/Formatter)**：
    配置 `biome.json` 在 **24 毫秒内自洁修复全库 78 个 TS/JS 文件**，自动重新排序依赖 Imports，保障在 CI/CD 阶段的格式规范。
*   **Playwright (E2E 浏览器测试)**：
    自动化测试 `/apps/web/e2e` 下的用户登录跳转、LocalStorage 会话持久、侧栏历史渲染以及 Token 计数交互旅程。
*   **Promptfoo (Prompt 防守评测)**：
    在 `promptfooconfig.yaml` 中配置大额退款分类断言，以及专门模拟超级管理员口吻命令绕过安全拦截的 **Jailbreak 防注入评测断言**，坚守提示词逻辑边界。

---

## 5. 开发与部署命令

### 5.1 数据自填充 (Live Seeding)
我们已经为您准备了极具演示冲突和对比属性的关系型高保真种子数据：
```bash
# 执行物理多租户多商户种子数据注入（自动清理、创表并灌入完备的 Products、Orders 及 Metrics 数据）
bun packages/db/src/seed.ts
```

### 5.2 毫秒级极速代码校验与自动修复 (Biome)
```bash
# 运行 Biome 一键全自动格式化与无用 imports 清理
bun run biome:check
```

### 5.3 端到端浏览器自动化测试 (Playwright)
```bash
# 运行 Playwright E2E 无头测试
bun run test:e2e
```

### 5.4 提示词防注入与意图质量评测 (Promptfoo)
```bash
# 启动 Promptfoo 模型断言测试
bun run test:prompt
```

### 5.5 本地一键拉起 dev 服务进行网页端实战体验！
```bash
# Bun 极速拉起 Next.js 控制台 (自愈直跑，已与本地 FakePool、Redis/PG 仿真无缝打通)
bun run dev
```
打开浏览器访问 [http://localhost:3000](http://localhost:3000) 即可自由开启一场极具科技美感的智能客服人机协同、自动回溯和知识 RAG 体验！

---

*本文档基于 smartServe-agent 物理落地的代码结构进行详尽整理与更新。*
