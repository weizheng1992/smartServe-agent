# 🚀 smartServe-agent: 双 Agent 智能体平台 —— 智能客服 + 商户数据分析 (v4 Architecture)

[![CI](https://github.com/weizheng1992/smartServe-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/weizheng1992/smartServe-agent/actions/workflows/ci.yml)

smartServe-agent 是基于 **Turborepo Monorepo**、**Python FastAPI 网关** 与 **LangGraph 双决策图** 构建的生产级多租户智能体平台。v4 在智能客服 Agent 之上新增**商户数据分析 Agent**（LLM 永不写 SQL 的语义层路线），并交付**优惠营销资金链**（建券→展示→领券→下单核销→统计对账）、**双端真实登录**、**RBAC 权限体系**与**小模型训练影子接入**全链路。

> 💡 **版本演进**：
>
> - **v4 双 Agent 平台（2026-09-19，wayfinder「商城/商户 data agent 双模块重构」收官）**：新增商户**数据分析 Agent**（14 指标语义注册表，LLM 只解析意图、永不写 SQL；sqlglot 四层安全闸；折线图/表格卡）；**优惠营销资金链**端到端（后台建三类活动→商城促销价/领券→下单自动算优惠+核销→客服对话可问→data agent 统计）；**`apps/merchant-admin` 独立商户后台**（真实登录+注册、RBAC 菜单/角色/员工三件套、六页全 CRUD、报告导出）；**小模型训练影子接入**（词表弱标注 590 句 → bge+线性头 heldout 98.9%，三态环境变量灰度）。详见 [ADR-0004](docs/adr/0004-semantic-layer-route-and-dual-agent-seam.md) 与 [训练文档](docs/training/metric-head-training.md)。
> - **v3.2 页面组件化（2026-09-19）**：merchant-admin 按菜单域文件夹全页面拆分（六 tab 工作台 1937 行 → 容器 855 行 + 五组件 + WorkbenchContext），Workbench 六 tab 门控修复（一次只渲染当前域）。
> - **v3.1 运营真实化（2026-09-07）**：真实登录（bcrypt+JWT）、限流、LLM 熔断/退避、评测真实入库。
> - **v3**：后端整体 Python 化（FastAPI 网关 + LangGraph 引擎 + SQLAlchemy/Alembic），44 条契约路由 pytest 钉死。
> - **v2 / v1**：分层中台重构 / 初代单体（分支 `v1-main`）。

---

## 🖥️ 四大终端 (Four Terminals)

| 终端 | 端口 | 面向 | 核心能力 |
|---|---|---|---|
| **apps/web** | 3000 | 终端用户（轻量） | 多模态聊天、富卡片、SSE 流式 |
| **apps/admin** | 3001 | SaaS 平台运维 | 11 大管控模块、HITL 审批、全链路 Trace |
| **apps/merchant** | 3005 | 商城消费者 | 极光潮品商城、悬浮客服、**真实登录/注册**、**促销价/领券** |
| **apps/merchant-admin** ⭐新 | 3006 | 商户员工/老板 | **数据分析 Agent**（悬浮+全屏）、订单/商品/客户 CRUD、优惠活动管理、RBAC 三件套、报告导出 |

⭐ `merchant-admin` 为 v4 新增独立应用（Vite 6 + React 19，组件库强制 `packages/ui`）：全局悬浮数据分析助手任意路由可唤起（上下文=当前路由+选中数据），六页全 CRUD，顶栏快捷切换员工身份。

---

## 🤖 双 Agent 架构 (Dual-Agent Architecture)

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                      apps/merchant-admin (Port 3006)                     │
│   数据分析全屏工作台 + 全局悬浮 Agent · RBAC 菜单/角色/员工 · 报告导出   │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ /api/admin/analytics/* (员工面 JWT)
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              商户数据分析 Agent (engine_py/analytics/, 独立轻管线)        │
│                                                                         │
│   intake(PageContext 选中实体)                                          │
│     → resolve: L0 词表归一 → 分类头(小模型缝②) → LLM 兜底反问           │
│     → compile: 指标模板闭集 + bindparams(业务口径烧在模板里)            │
│     → execute: 只读 reader 引擎(READ ONLY + 3s 超时 + SAVEPOINT)        │
│     → 卡片: 表格/折线图(SVG) + 口径注记                                 │
│                                                                         │
│   14 指标: 销售5族/差评榜/退款率/售后/会话量/AI解决率/活动核销/优惠总额  │
│   兜底分发器: LLM 不可达时优惠/券/订单状态仍确定性真答                   │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ (与商城客服 Agent 共享: 会话/推送/卡片约定)
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│            智能客服 Agent (graph/ + triage/ + skills/, LangGraph)        │
│   triage(意图分流+槽位) → planner → executor ⇄ validator → finish       │
│   + PromotionQuerySkill(优惠/券问答) + 语义缓存 + ApprovalGatekeeper    │
└─────────────────────────────────────────────────────────────────────────┘
```

> **为什么 LLM 永不写 SQL**：数据 agent 的 LLM 只负责把口语解析为闭集结构化意图（指标/维度/方向/时间窗），SQL 由指标模板确定性拼装（口径烧在模板里，退款单不可能混进销量）。实测依据与二期演化缝见 [ADR-0004](docs/adr/0004-semantic-layer-route-and-dual-agent-seam.md)。

---

## 🎁 优惠营销资金链 (Promotion Lifecycle)

```
商户后台建活动(满减/折扣/券, RBAC 限老板/运营)
    ↓
商城首页横幅 + 商品促销价(服务端唯一算价) + 商品页领券(用户级券实例)
    ↓
下单结算: 自动匹配最优活动(券 vs 满减取大, SAVEPOINT 隔离)
          实付 = 原价 − 优惠, promotion_redemptions 核销落库
    ↓
客服对话: 「有什么优惠活动」「我的优惠券」→ PromotionQuerySkill 真答
    ↓
data agent: 「各活动核销订单数」「优惠总额」→ 与造数逐笔对账
```

---

## 🧠 小模型训练与影子接入 (Small Model Pipeline)

```text
词表弱标注(590 句×11 类, seed_from_registry.py)
    → prepare_data(去重 + 评测近邻过滤 cos≥0.90 + 分层切分)
    → train(bge 冻结编码 + torch 线性头, CPU 2 分钟)
    → evaluate(heldout accuracy 98.88% / macro F1 0.907)
    → 部署: AI_METRIC_HEAD=shadow(并行打分记日志) → on(L0 未命中处接管)
    回滚 = 移除环境变量
```

- 数据水龙头：`scripts/export_intent_data.py`（intent_logs/badcase 持续积累，真实库已 1966+ 行）
- 完整文档：[docs/training/metric-head-training.md](docs/training/metric-head-training.md)（数据源/格式/库/参数/部署全链路）
- 训练脚手架：`services/engine-py/scripts/training/`（README 含复现三命令）

### 🎯 SFT 轨（SemQL 意图解析，2026-09-21 已跑通）

```text
sft_dataset(词面 × 时间窗 × 品类 × limit 程序化组合, 4478 条, 评测纯门零泄漏)
    → 云训(PAI-DSW 免费包 A10 单卡, QLoRA nf4, 1680 步 23:49 完整跑完)
    → vLLM 自测三问槽位全中(含"卖得最差"→ASC 方向翻转 08-P1 回归门)
    → 部署: vLLM/Ollama 端点 → AI_BASE_URL 切换(影子跑 → promptfoo 达标)
    回滚 = 环境变量改回一行
```

- **训练结果**：loss 1.38→0.012 平台、token 准确率 99.6%；标准 transformers+peft+trl 栈（unsloth 补丁层注入坏 eos 已弃用）；adapter 154MB 不入库（gitignore，备份在本地 zip 与云端实例）
- **训练实录**（三坑排障 / 计算时账 ≈45/250 / 自测实录）：[docs/pai-dsw-sft-run-20260920.md](docs/pai-dsw-sft-run-20260920.md)
- **部署测评指南**（vLLM 自测 / 本地 Ollama / PAI-EAS / 42 条字段准确率脚本）：[docs/sft-deploy-eval.md](docs/sft-deploy-eval.md)
- 双轨总览：`services/engine-py/scripts/training/README.md`

---

## 📁 目录结构 (Monorepo Layout)

```text
├── apps/
│   ├── admin/               # SaaS 控制平面 (Port 3001, 11 大管控模块)
│   ├── merchant/            # 商城消费者端 (Port 3005, 真实登录/促销价/领券)
│   ├── merchant-admin/ ⭐   # 商户独立后台 (Port 3006, 按菜单域文件夹组织)
│   │   └── src/pages/
│   │       ├── login/               # 真实登录(bcrypt+JWT)
│   │       ├── analytics/           # 数据分析全屏工作台(components/问答渲染)
│   │       ├── reports/             # 我的报告(CSV 导出)
│   │       ├── order-manager/       # 六 tab 工作台(index 容器 855 行
│   │       │   ├── workbench.tsx    #  + workbench 状态 Context 504 行
│   │       │   └── components/      #  + orders/approvals/live-desk/spus/skus/spi-logs 六组件)
│   │       ├── goods/products/      # 商品 CRUD(增删改+下架+成交护栏)
│   │       ├── customers/           # 客户管理(消费排序+会员级改即存)
│   │       ├── promotions/          # 优惠活动 CRUD+核销(components/核销面板)
│   │       └── system/{menus,roles,staff}/  # RBAC 三件套
│   └── web/                 # 轻量客服端 (Port 3000)
│
├── services/
│   ├── gateway-py/          # FastAPI 网关 (Port 4000, 170 pytest)
│   │   └── src/gateway_py/routers/
│   │       ├── analytics.py # /api/admin/analytics/*(22 条: ask SSE/menus/roles/staff/reports/promotions)
│   │       └── auth.py      # login/logout/me/register(注册联动客户档案)
│   └── engine-py/           # LangGraph 决策引擎 (790 pytest)
│       └── src/engine_py/
│           ├── analytics/   # ⭐ data agent 域(独立轻管线)
│           │   ├── engine.py            # MetricQueryEngine(resolve/compile/execute)
│           │   ├── sql_guard.py         # sqlglot 四层安全闸
│           │   ├── schema_cards.py      # 商户库 schema 卡片
│           │   ├── metric_head.py       # 小模型影子接入(缝②)
│           │   ├── promotion_engine.py  # 优惠规则计算(服务端唯一算价点)
│           │   ├── promotions.py        # 活动 CRUD+核销+审计
│           │   ├── rbac.py              # RBAC 菜单树/角色分配/员工
│           │   ├── report_service.py    # 报告生成(HTML+CSV)
│           │   ├── graph.py             # data agent 轻图
│           │   ├── exemplar_service.py  # query_exemplars L2 示例
│           │   └── fallback_dispatcher.py  # LLM 不可达确定性兜底
│           ├── skills/promotion_skill.py    # 客服对话优惠问答技能
│           ├── triage/metric_head.py        # 意图分类头缝①(影子接入)
│           ├── scripts/training/            # 训练脚手架(README 全文档)
│           ├── scripts/export_intent_data.py  # 数据水龙头 CLI
│           └── training_runs/metric_head/   # 训练产物(head.pt+曲线)
│
├── packages/{types,ui}/     # 冻结契约类型 + 共享 UI 组件库
├── eval/                    # promptfoo 评测(意图/多意图/数据Mapping + providers)
├── docs/
│   ├── specs/mall-data-agent-split.md   # 双模块重构 spec(ready-for-agent)
│   ├── adr/0004-*.md                    # 语义层路线与双 Agent 模块缝
│   ├── adr/0005-*.md                    # data agent LLM 意图(并行会话)
│   ├── training/metric-head-training.md # 小模型训练完整文档
│   └── wayfinder/mall-data-agent-split/ # 规划图谱(20 决策票全档)
└── scripts/                 # 数据水龙头等工具脚本
```

---

## 🔌 核心基础设施 (Platform Core)

以下平台核心能力自 v3 起稳定，深度设计详见 `docs/architecture/` 与对应 ADR：

- **客服 Agent 决策图**：triage(意图分流+咨询直答快轨) → planner(规划/快轨) → executor ⇄ validator → finish；确定性兜底分发器（LLM 不可达时优惠/券/订单状态仍真答）。
- **HITL 审批**：ApprovalGatekeeper（双退款/阈值/高额改址拦截）+ Transactional Outbox 对账 + Temporal 周期任务。
- **四层记忆**：short/long/episodic/task（AgentMemoryEngine 统一收集与落盘）。
- **Contextual RAG**：BM25+向量+RRF 混合检索，知识文件自愈补灌。
- **参数化 SQL 沙箱**：sqlglot AST 只读审计 + `READ ONLY` 事务 + 超时熔断 + `LIMIT` 约束。
- **多租户隔离**：business_id 强制过滤、PII 递归脱敏、SQL 下推隔离。
- **实时协同**：Redis Streams 事件主干 + Last-Event-ID SSE 回放 + socket.io 坐席接管。
- **开放 SPI**：HMAC-SHA256 签名 + 防重放，对接商户私有 ERP/WMS。

---

## 🧪 测试 (Testing, 全量绿)

| 套件 | 数量 | 覆盖 |
|---|---|---|
| engine pytest | **790** | 意图仲裁/视觉消歧/记忆/优惠引擎/golden SQL/兜底分发器/ RBAC/报告/数据水龙头/训练流水线 |
| gateway pytest | **170** | HTTP/SSE/socket.io 契约 + AST 沙箱 + analytics 路由(ask SSE/RBAC/报告/核销幂等) |
| merchant-admin E2E | **11** | 登录门卫/RBAC 菜单/六胶囊真答/悬浮 agent/报告/优惠 CRUD |
| merchant-admin vitest | **29** | 菜单树/SKU 库存/客户抽屉/活动范围 |
| promptfoo | 就绪 | 意图分类/多意图(含 promotion_query 6 例)/数据 Mapping 8 例 — 分类器用例需模型代理(11211)在线 |

```bash
bun run test:engine        # engine 全量 (790)
bun run test:eval          # gateway 全量 (170)
bun run test:e2e           # Playwright E2E
bun run test:prompt        # promptfoo 意图评估
cd apps/merchant-admin && bun run build   # tsc + vite
```

---

## 🚀 快速启动 (Quick Start)

```bash
bun install && uv sync                    # 依赖(services/ 下 uv sync)
cp .env.example .env                      # LLM/DB/Redis 凭据
bun run docker:up                         # PostgreSQL + Redis
bun run db:push && bun run db:seed        # 迁移 + 种子(含测试账号 test@example.com / agent-all-dev)

bun run dev:all                           # 一键: web(3000) admin(3001) gateway(4000) merchant(3005)
cd apps/merchant-admin && bun run dev     # ⭐ 商户后台 (Port 3006)
bun run worker                            # Temporal Worker(周期任务)
```

| 服务 | 地址 | 说明 |
|---|---|---|
| apps/web | :3000 | 轻量客服端 |
| apps/admin | :3001 | SaaS 控制平面 |
| apps/merchant | :3005 | 商城消费者端(真实登录) |
| **apps/merchant-admin** | **:3006** | **商户后台(数据分析/优惠/RBAC)** |
| gateway-py | :4000 | FastAPI 网关 |

---

## 📚 深度文档 (Deep Docs)

| 文档 | 内容 |
|---|---|
| [双模块重构 spec](docs/specs/mall-data-agent-split.md) | v4 全量规格(ready-for-agent, 含六阶段排期) |
| [ADR-0004](docs/adr/0004-semantic-layer-route-and-dual-agent-seam.md) | 语义层路线(LLM 永不写 SQL)+双 Agent 模块缝 |
| [ADR-0005](docs/adr/0005-data-agent-llm-intent-and-growth-loop.md) | L3 LLM 意图兜底 + 覆盖增长机制(未命中落库) |
| [ADR-0006](docs/adr/0006-data-agent-architecture-comparison.md) | **架构对照:LangGraph+MetaRAG+GRPO 全家桶提案 vs 语义层轻管线**——逐层采用/暂不采用/明确不采用的理由与重新评估触发器 |
| [训练文档](docs/training/metric-head-training.md) | 小模型数据源/格式/库/参数/部署全链路 |
| [wayfinder 图谱](docs/wayfinder/mall-data-agent-split/map.md) | 20 张决策票完整推导(实现期歧义以票为源) |
| [商户接入指南](docs/merchant-onboarding-guide.md) | SPI 对接/RAG 灌入/审批策略 |
| [架构深度指南](docs/architecture/) | RAG/HITL 重规划/弹性部署 |
| **[生产部署方案](docs/deploy.md)** | **Docker Compose 全栈上线:四前端 nginx 一体/gateway/PG/Redis/Temporal,五步上线+运维+安全清单** |

---

## 📄 历史版本

- **v3.2 / v3.1 / v3 / v2 / v1**：见 [CHANGELOG.md](CHANGELOG.md) 与 git tag（v1 在分支 `v1-main`）。
