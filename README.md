# 🚀 smartServe-agent: 双 Agent 智能体平台 —— 智能客服 + 商户数据分析 (v4 Architecture)

[![CI](https://github.com/weizheng1992/smartServe-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/weizheng1992/smartServe-agent/actions/workflows/ci.yml)

smartServe-agent 是基于 **Turborepo Monorepo**、**Python FastAPI 网关**（134 条注册端点，live OpenAPI 验证）与 **LangGraph 双决策图** 构建的生产级多租户智能体平台。v4 在智能客服 Agent 之上新增**商户数据分析 Agent**（语义层分层信任路线:T0 核验/T1 组合/T2 探索三通道，LLM 永不在无守卫、无标注的情况下产 SQL），并交付**优惠营销资金链**（建券→展示→领券→下单核销→统计对账）、**双端真实登录**、**RBAC 权限体系**与**小模型训练影子接入**全链路。**v5 规划（main 开发线）:本体知识层重构**——领域知识收口为声明式本体知识层（Palantir 式对象-动作语义层，现代栈），见下文「🧬 v5 规划:本体知识层重构」专节（位于平台实览上方）。

---

## 🧬 v5 规划:本体知识层重构 (Ontology Knowledge Layer)

> **状态:规划已裁决(2026-10-19),批〇待启动。** 本节是重构的完整方案:为什么、重构成什么、如何分批、买到什么、用什么技术。方案裁决由 17 个并行 agent 对全仓取证驱动(7 路子系统调研 + 3 案对案 + 五轴裁判 + 5 透镜对抗烤问 + 完整性补漏);技术时效与选型边界另经 4 路网络调研实查(2026-10,一手来源 GitHub/PyPI/官方博客,关键数字见 5️⃣)。

### 1️⃣ 为什么重构 (Why)

**病根:领域知识散装五处,同一词汇多形态并存,漂移已四次实弹。**

| 领域知识 | 现在住在哪(散装) | 已实弹的病 |
|---|---|---|
| 实体+关系 | `semantic_model.yaml`(12 实体)+ `schema_cards.py` 手抄列卡 | 手抄卡漂移:`membership` ≠ 真列 `member_level`,**错卡正喂进 Data Agent T2 接地 LLM prompt**(对模型说谎) |
| 动作面 | `approval_actions.py` frozenset + gatekeeper 隐式 if/elif + ui TS union + types 冻结契约 = **四形态并存** | TS union 多了幽灵动作 `reply`(后端不受理)又漏登实发的 `start_human_takeover`/`release_takeover`;商户台无白名单 + 引擎 else 兜底 → **拼错动作字符串 = 真实退款工单被静默驳回** |
| 资金阈值 | 免签退款限额缺省散落六处 | 50(tenant_config/order_skills/base_skill)vs 100(执行器两处 or-100/gatekeeper 形参)vs 租户装配 nike=150/adidas=120 —— **同一笔 80 元退款,走技能快轨挂人工、走执行器工具路直接免签,资金闸行为取决于代码路径而非金额** |
| 不变量 | 散在测试断言与注释(FK 域闭包/受理集/阈值单源) | 无声明载体,新增代码不知道它们存在 |
| 表所有权 | `merchant_access.py:19` 一行 docstring 禁令 | 零机械闸,违规零红灯 |
| DDL 真相 | `_MERCHANT_DDL` + schema manifest + seed_helpers **三份副本** | 加列须三处同步(曾一次 43 个下游测试连挂) |

**根因诊断:四起实弹全是校验问题,不是表示问题**——不是知识没写下来,是写下来的地方没人抄得齐。解法只有一个方向:单一事实源 + 机器闭合校验,让漂移**结构性不可能**。

### 2️⃣ 重构成什么 (Target)

**形态定位(2026-10 产业实查)**:这套东西在业界有正式名字——**semantic layer(语义层)+ schema grounding**;「ontology for AI agents」在 2025-2026 产业语境的主流所指是 **Palantir 式对象-动作操作本体**(object type / link type / action type,a16z 2026-01《The Palantirization of everything》将其钉为 agent 生产化的护城河模板),**不是 W3C RDF/OWL**。本方案正是其同构缩小版:实体+表列映射 ≈ object type、动作面 ≈ action type、AST 守卫+闭集模板 ≈「agent 不拿数据库凭据、只消费受治理语义面」的设计公理。

仓库根新顶层目录,与 `apps/ services/ packages/` 平级。**定位是 monorepo 知识资产(同 `packages/types` 一类),不是独立后端服务**——无进程无端口无部署,uv workspace 成员,engine/gateway 进程内 import 消费:

```text
ontology/
├── core.yaml                    ← 核心词汇:Agent/Action/Face/Domain 基础类型与枚举
├── domain/                      ← 领域层(四域:实体+属性+表列映射)
│   ├── product.yaml             │   SPU / SKU / Review
│   ├── trading.yaml             │   Order / OrderItem / Settlement
│   ├── marketing.yaml           │   Promotion / UserCoupon / Redemption
│   └── crm.yaml                 │   Customer / MembershipLevel
├── application/                 ← 应用层(任务面)
│   ├── actions.yaml             │   动作面:审批动作+业务写操作+结算复合条目
│   │                            │   (faces 面曝光/permission 权限码/幂等形态;
│   │                            │    checkout 声明 spans 三域+single-conn-single-tx)
│   ├── intents.yaml             │   17 意图闭集
│   └── metrics.yaml             │   39 指标
├── registry.py                  ← pydantic v2 声明模型+加载校验(坏声明进程起不来)
├── generated/{py,ts}/           ← 双语代码生成物(Python 常量+TS 契约包;CI 校验同步)
├── cards/                       ← LLM 接地 schema 卡(由 domain 层派生,喂 Data Agent T2)
├── tests/                       ← 一致性门(pytest)+ 跨文件交叉断言
├── exports/                     ← 可选导出面:property-graph schema / JSON-LD / MCP 工具面(升级路)
└── CHANGELOG.md
```

**三条分层裁定**(对抗烤问后钉死,防「本体过度化」):

1. **平台级一份本体**——全租户共享一份;aurora/nike/adidas 等租户差异(阈值/货架词典/技能开关)是**配置数据**(tenant_configs),不进本体。对应既有 global/tenant 双层画像分层。商城与后台管理也不各建一份——它们是应用层动作的 **faces 曝光面**(customer/operator/spi/staff_review),四个前端消费同一本体的不同投影。
2. **业务数据永远留在 PG**——知识层只存 schema/契约声明(数百行),实例数据零复制;实体-表映射声明驱动 schema 卡与 DDL manifest 对拍。
3. **数据三个来源**:声明开发者手写、PR 演进(即今天手写 yaml/frozenset 的收口,不是新造知识);实例留库;动态词汇(货架品类词等)运行时跟库,不钉死声明。

### 3️⃣ 如何重构 (How:四批,各自独立可交付、可回退)

| 批 | 内容 | 人日 | 有意测试红 |
|---|---|---|---|
| **批〇·试点** | 目录 + core.yaml + marketing 单域 + registry.py(pydantic v2 声明模型与加载校验)编译回现有 frozenset/实体结构 + 一致性门进 pytest——先证明「声明→运行时→测试」环闭合 | 2-3 | 近零 |
| **批一·动作面收口** | 四域全量 + 应用层 + 三面路由闸改读编译产物 + **四实弹修复**(静默驳回→400 / 阈值六处单源=50 / 幽灵登记 / 列漂移勘正) | 4-5 | 3-6 改 + 4 增(契约修订) |
| **批二·映射接管** | 实体-表映射声明全面接管 schema 卡与 manifest 对拍(DDL 三份真相收一);generated/ts 生成 + 前端契约册重钉为钉生成器 | 3-4 | 2-4(漂移浮出即目的) |
| **批三·治理面** | 词汇全量 + 知识层文档自动生成(Mermaid/Markdown 知识地图)+ CI regen 门 + ADR-0015(「本体知识层」决策全文) | 1-2 | 近零 |

**消费机制——运行时零额外开销:**

| 时机 | 机制 |
|---|---|
| import 期 | registry.py 解析全部声明,**编译成与今天一模一样的 Python 常量**(frozenset/实体表/阈值)——请求路径性能零变化 |
| 测试期 | pydantic 校验 + 交叉断言册(受理集 parity / 面⊆闭集 / 权限码必须真实 / TS 双向对齐),坏声明/漂移 pytest 红 |
| 构建期 | generated/ts → 前端契约包;CI regen 后 `git diff --exit-code` 防手改 |
| 接地期 | cards/ 派生 schema 卡喂 Data Agent T2 探索(产业所谓 schema grounding) |

**不动清单(对抗烤问的否决项,防范围蠕变):** 结算核/技能/图管线/134 端点/SSE 线格式**零行为变化**(checkout 的事务语义只被声明、不被触碰);不物理拆库不拆 schema(取证:`_commit_order` 单连接单事务横跨三域,saga 补偿组件零存量,物理拆 = 分布式事务残局);不拆售前/售后 agent(复合轮/记忆/恢复缝成本高收益低);不引图数据库/SPARQL 服务/第三方记忆产品(理由见 5️⃣)。

### 4️⃣ 重构好处 (Benefits)

1. **漂移结构性不可能**:动作词汇四形态收一、列卡手抄改投影,任何新漂移在一致性门 / CI regen 门红灯,不再靠人肉对齐;
2. **DDL 三份真相收一**:schema manifest 与 seed 列清单从映射声明派生,「加列一处改、三处红」的年代结束;
3. **三面口径统一**:admin/SPI/商户台共用同一受理集投影,未知动作 400 诚实报错(现状:静默驳回真实退款工单);
4. **资金闸单源**:免签阈值缺省唯一声明(50,收紧方向;租户覆写通道语义不变)——80 元退款不再因代码路径不同而结局不同;
5. **schema grounding(产业共识做法)**:映射派生的 schema 卡喂 Data Agent T2——text2SQL 第一瓶颈的公认解法,根治「错卡对模型说谎」;
6. **LLM-in-the-loop 演化门**:新意图/新动作先过一致性门再上线(声明式约束 + pytest,拿到 SHACL 式闭合校验的收益而无其生态成本);
7. **知识地图自动生成**:Mermaid/Markdown 文档随声明派生,可展示物 +1;
8. **可评测 + MCP 就绪**:一致性门是 pytest 断言面;同一注册表未来可再编译一份 MCP 工具面(2026 年 agent 消费语义层的事实接口,Cube/Brex 范式)。

### 5️⃣ 使用的技术 (2026-10 实查)

**选型定位**:本方案站在 2025-2026 产业共识正中央——**semantic layer × schema grounding × Palantir 式对象-动作本体**。产业背书:dbt 2026-04 基准(语义层内查询准确率 98.2-100% vs 裸 text2SQL 84-90%,且语义层答不了会报错、从不静默返回错数);Cube 2026-06《Semantic Layer for AI Agents》六控制点(compile-time governance / 按名选认证指标 / 结果带证据)与本仓「服务端模板注入租户谓词 + LLM 永不写 SQL」逐点同构;dbt 已开源 MetricFlow(2025-10,Apache 2.0),ODCS 数据契约标准 v3.2 于 2025-12 完成产业收口——声明式 YAML 契约正是产业形态。

| 技术 | 角色 | 2026-10 实查状态 |
|---|---|---|
| 分层 YAML 声明 + **pydantic v2** | 声明与加载校验 | 现代 Python 事实标准;Palantir Ontology / ODCS v3.2 数据契约同为声明式形态 |
| 双语 codegen(Python 常量 + TS 契约包) | 单一事实源分发 | schema-first 工程主流;dbt MetricFlow 同思路 |
| schema 卡接地 | LLM 接地 | schema grounding = text2SQL 第一瓶颈的公认解法(COLING 2025 Solid-SQL 等) |
| MCP 工具面(可选增量) | agent 消费面 | 2026 事实标准接口(Cube 2025-05 MCP 集成;Brex 同范式嵌入式 AI 分析师) |
| known-answer evals(可选增量) | 评测 | Cube 六控制点之一;本仓 promptfoo/nightly 体系现成 |

**为什么不用 Neo4j 等图数据库**(行业共识实查):

1. **层错位**——图数据库是数据面技术(海量实例节点的多跳遍历 / Cypher 消费方);本层是知识/契约面(数百行声明编译成常量,零运行时图查询消费方),精确命中行业「过度设计」清单全部四条:查询可用固定 JOIN 表达、遍历浅、数据以结构化为主、真数据已在关系库;
2. **「GraphRAG 需要图形状数据,不需要图数据库」**——微软 GraphRAG 官方实现的知识图谱全落 parquet 平文件(官方 discussion #641);四家主流工具(GraphRAG v3.3.0 / LightRAG v1.5.7 / LlamaIndex PropertyGraphIndex)默认图存储全是内存/文件,Neo4j 皆为可选生产后端,LightRAG 生产推荐甚至是 PostgreSQL;
3. **同步税**——PG→Neo4j 主流方案是 Debezium+Kafka CDC 管道:供养一条分布式系统、强一致降级为最终一致、租户谓词注入需在图侧重建——恰是本次要消灭的「多份真相漂移」的放大版;
4. **升级触发(届时直接上 Neo4j 2026.x + neo4j-graphrag 1.x→2.0)**——出现真实的多跳实例图消费方(反欺诈关联网络类),或非结构化语料 GraphRAG 正式上马。

**为什么不用 Zep/Graphiti、mem0、Letta 等记忆产品**:mem0 OSS v3(2026-09)已把图记忆整体移出开源版转托管付费,且 SaaS 形态与多租户数据不出域的不变量冲突;Letta 2026-03 战略转向 coding-agent 运行时、服务端记忆 API 退役中;Graphiti(双时相知识图,v0.31.1)形态最正,但意味着新增 Neo4j/FalkorDB 基础设施 + 每 episode 一次 LLM 结构化抽取的成本。本仓自建四象限记忆无实弹痛点;触发信号(两条以上再评估):as-of 时间旅行查询成为硬需求 / 记忆事实过期失效成为实弹 bug。

**为什么不用 W3C RDF/OWL/SHACL 全栈**:RDF 1.2 截至本月仍在 CR/WD 阶段未成正式推荐标准,rdflib 对其新特性支持仍在分阶段;SHACL 1.2 规则轨道两派竞争未定;数百行声明用该栈是负收益。**借词不借栈**:声明式约束 + 编译期常量 + pytest 契约,即拿到闭合校验的全部收益而无其生态成本。(勘误:此前草案提过的「OWL 2 CD」并非真实标准。)

> 选型一句话:**站在产业共识正中央(Palantir 式对象-动作本体 × semantic layer × schema grounding),借 GraphRAG 的思想、不搬它的栈;每个组件在本仓库有真实消费方——零消费方的新能力是负债,不是升级。**

---

## 📸 平台实览 (Screenshots)

**⭐ 商户数据分析 Agent** — `apps/merchant-admin` (Port 3006):全屏分析工作台 + 全局悬浮助手（上下文感知，任意路由可唤起），ResultCard 同形渲染——图表 + 数据表 + 口径注记 + AI 速览 + CSV 导出：

![商户数据分析 Agent:分析工作台 + 悬浮助手](docs/assets/readme/merchant-admin-analytics.png)

| 客户端聊天 + LangGraph DAG 实时监控 (`apps/web`) | 商城消费者端 + 悬浮智能客服 (`apps/merchant`) |
|---|---|
| ![客户端聊天与 DAG 执行监控](docs/assets/readme/web-chat.png) | ![商城与悬浮客服](docs/assets/readme/merchant-shop.png) |

| SaaS 管控台 · 全局大盘 (`apps/admin`) | HITL 审批与风控审计 (`apps/admin`) |
|---|---|
| ![SaaS 管控台全局大盘](docs/assets/readme/admin-dashboard.png) | ![HITL 审批与风控审计](docs/assets/readme/admin-hitl.png) |

> 左上图:`apps/web` 右栏为 **有向有环图(DAG)实时执行监控**——triage/planner/executor/validator 每个节点的执行反馈逐条直播；右上图：商城悬浮客服真答订单查询（订单列表卡 + 追问建议）。左下图：管控台大盘全部指标**库内真算**（session_metrics / pending_approvals / threads / llm_call_logs）；右下图：HITL 审批工单全量留痕（超阈值退款拦截、人工接管结案）。

---

## 💡 版本演进

- **v5 标准本体层重构（2026-10-19 规划裁决，在 main 开发线实施；v4 线存档于分支 `v4-main`）**：领域知识从**五处散装**（2 份 yaml + 手抄 schema 卡 / 动作词表四形态并存 / 散装不变量 / 一行注释的所有权禁令 / DDL 三份真相）收口为 **声明式本体知识层**——仓库根新顶层 `ontology/`：核心词汇 + 四域 + 应用层（动作/意图/指标）分层声明，pydantic v2 加载校验，编译期产出 Python 常量与 TS 契约包，schema 卡喂 LLM 接地；MCP 工具面与图导出为可选升级路。运行时 import 期编译为常量（零运行时开销），一致性门进 pytest；**平台级一份本体**（租户差异留 tenant_configs，业务数据留 PG）。技术时效经 2026-10 实查定调：该形态即产业主流——semantic layer × schema grounding × Palantir 式对象-动作本体；Neo4j 等图数据库与 W3C RDF 栈经适用边界调研明确不用（理由见专节 5️⃣）。动因是四起实弹取证：商户台未知动作**静默驳回真实退款工单**、免签退款阈值**六处缺省分叉**（同一笔 80 元退款因代码路径不同结局不同）、schema 卡列漂移正喂 T2 接地 LLM prompt、TS 冻结面幽灵动作。分四批落地（10-14 人日），详见下文专节；ADR-0015 随批〇落笔。
- **v4.1 分层信任架构（2026-10-07，即 [CHANGELOG](CHANGELOG.md) [2.7.0]；[ADR-0010](docs/adr/0010-tiered-trust-architecture.md)/[ADR-0011](docs/adr/0011-attribution-phase-b-boundary.md) 落地）**：data agent 升级**分层信任梯度**——语义层单一事实源（`tools_registry/semantic_model.yaml` 12 实体/9 join/8 维度，`semantic_model.py` 加载即校验 + `semantic_compiler.py` 声明编译器，23 规整族迁声明编译、13 bespoke 族债务清单逃生舱）；**T1 组合通道**（`AI_T1_COMPOSE=on` 灰度：LLM 产 CompositionQuery、编译器拼 SQL；**语感直通** breakdown_reroute——「各品牌净销售额」零 LLM 升格组合；**时间平移** compare_previous 双期 CTE）与 **T2 探索通道**（`AI_T2_EXPLORE=on` ∧ admin/finance_owner 双闸：LLM 接地生成 SQL 过守卫链强制审计，`generatedSql` 折叠可审）先后开闸，结果卡三档信任章（verified/composed/explored）；**归因卡**（本期 vs 上期贡献度分解 + 退款率对照列 + AI 叙事隔离章，叙事数字可溯源硬校验，`AI_ATTR_NARRATIVE` 默认关）；闭集 39 指标（新增 net_sales 净销售额）+ 品牌/区域/城市维度；答案反馈闭环 👍/👎（第 40 条路由，traceId 台账/坏例池扇出）；意图评测语料 101 → **572 句**。
- **v4 双 Agent 平台（2026-09-19，wayfinder「商城/商户 data agent 双模块重构」收官）**：新增商户**数据分析 Agent**（14 指标语义注册表起步，LLM 只解析意图、永不写 SQL；sqlglot 四层安全闸；折线图/表格卡）；**优惠营销资金链**端到端（后台建三类活动→商城促销价/领券→下单自动算优惠+核销→客服对话可问→data agent 统计）；**`apps/merchant-admin` 独立商户后台**（真实登录+注册、RBAC 菜单/角色/员工三件套、六页全 CRUD、报告导出）；**小模型训练影子接入**（词表弱标注 590 句 → bge+线性头 heldout 98.9%，三态环境变量灰度）。详见 [ADR-0004](docs/adr/0004-semantic-layer-route-and-dual-agent-seam.md) 与 [训练文档](docs/training/metric-head-training.md)。
- **v3.2 页面组件化（2026-09-19）**：merchant-admin 按菜单域文件夹全页面拆分，Workbench 多 tab 门控（一次只渲染当前域）。
- **v3.1 运营真实化（2026-09-07）**：真实登录（bcrypt+JWT）、限流、LLM 熔断/退避、评测真实入库。
- **v3**：后端整体 Python 化（FastAPI 网关 + LangGraph 引擎 + SQLAlchemy/Alembic），契约路由 pytest 钉死。
- **v2 / v1**：分层中台重构 / 初代单体（分支 `v1-main`）。

> 逐版本明细见 [CHANGELOG.md](CHANGELOG.md)（2.6.x 为 v4 收官后的日粒度演进：夜间评测基建、run_agent 性能批、双退款 TOCTOU、mall_domain 神类拆解、审批 SETNX 误判修复等）。

---

## 🖥️ 四大终端 (Four Terminals)

| 终端 | 端口 | 面向 | 核心能力 |
|---|---|---|---|
| **apps/web** | 3000 | 终端用户（轻量） | 多模态聊天、富卡片、SSE 流式、DAG 执行监控 |
| **apps/admin** | 3001 | SaaS 平台运维 | 11 大管控模块、HITL 审批、全景会话回放、全链路 Trace |
| **apps/merchant** | 3005 | 商城消费者 | 极光潮品商城、悬浮客服、**真实登录/注册**、**促销价/领券** |
| **apps/merchant-admin** | 3006 | 商户员工/老板 | **数据分析 Agent**（悬浮+全屏+数据看板）、订单/商品/客户 CRUD、优惠活动管理、RBAC 三件套、报告导出 |

`merchant-admin` 为 v4 新增独立应用（Vite 6 + React 19，组件库强制 `packages/ui`）：全局悬浮数据分析助手任意路由可唤起（上下文=当前路由+选中数据），按菜单域组织页面，老板可快捷切换员工身份。

---

## 🤖 双 Agent 架构 (Dual-Agent Architecture)

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                      apps/merchant-admin (Port 3006)                     │
│   数据分析全屏工作台 + 全局悬浮 Agent · RBAC 菜单/角色/员工 · 报告导出   │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ /api/admin/analytics/* (员工面 JWT, 40 条路由)
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              商户数据分析 Agent (engine_py/analytics/, 独立轻管线)        │
│                                                                         │
│   intake(PageContext 选中实体)                                          │
│     → resolve: L0 词表归一 → 分类头(小模型缝②) → LLM 兜底反问           │
│     → compile: 语义模型声明编译(23 规整族) + 13 bespoke 族手写模板      │
│     → execute: 只读 reader 引擎(READ ONLY + 超时 + SAVEPOINT)           │
│     → 卡片: 表格/折线图(SVG) + 口径注记 + 三档信任章                     │
│                                                                         │
│   39 指标 × 8 域 + 语义模型(12 实体/9 join/8 维度)                      │
│   意图分层: L0 词表 → 小模型分类头 → L2 范例回放 → L3 LLM/SFT 兜底     │
│   全层未命中 → T1 组合(语感直通/LLM) → T2 探索(守卫链) → 响亮失败      │
│   落 agent_unanswered(覆盖增长闭环,不编造答案);归因卡(贡献度分解)     │
│   👍/👎 反馈闭环(traceId → 台账/坏例池)                                │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ (与商城客服 Agent 共享: 会话/推送/卡片约定)
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│            智能客服 Agent (graph/ + triage/ + skills/, LangGraph)        │
│   triage(意图分流+槽位) → planner → executor ⇄ validator → finish       │
│   + PromotionQuerySkill(优惠/券问答) + 语义缓存 + ApprovalGatekeeper    │
└─────────────────────────────────────────────────────────────────────────┘
```

> **为什么 LLM 永不写 SQL**：数据 agent 的 LLM 只负责把口语解析为闭集结构化意图（指标/维度/方向/时间窗），SQL 由语义编译器确定性拼装（口径烧在声明里，退款单不可能混进销量）。T2 探索通道是唯一例外——LLM 接地生成的 SQL 必须过 sqlglot 守卫链强制审计（围栏剥离 → ParseError 归类响亮拒绝 → LIMIT 强制 → 表白名单 → 只读 reader）。路线论证见 [ADR-0004](docs/adr/0004-semantic-layer-route-and-dual-agent-seam.md)，分层信任演进见 [ADR-0010](docs/adr/0010-tiered-trust-architecture.md)。

---

## 🎁 优惠营销资金链 (Promotion Lifecycle)

```text
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

- 数据水龙头：`services/engine-py/src/engine_py/intent_flywheel/export_intent_data.py`（`python -m engine_py.intent_flywheel.export_intent_data`；intent_logs/badcase 持续积累按时间窗导出 JSONL）
- 意图评测语料：`services/engine-py/evals/intent_cases.jsonl`（**572 句**：槽位程序生成 + 65 条 T2 型长尾，词面碰撞检查）
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

仅列目录层级（全部目录，不含文件）；各目录职责见注释。

```text
smartServe-agent/
├── apps/                                  # 四大前端 (Vite 6 + React 19, Bun workspaces)
│   ├── admin/                             # SaaS 控制平面 (Port 3001)
│   │   ├── src/pages/                     #   11 大管控模块,每模块一目录(多数带 components/)
│   │   │   ├── dashboard/                 #     全局大盘(指标库内真算)
│   │   │   ├── tenants/                   #     商户租户管理
│   │   │   ├── conversations/             #     全景会话回放
│   │   │   ├── audits/                    #     审批与风控审计(HITL)
│   │   │   ├── personas/                  #     人物画像事实素描
│   │   │   ├── rag-studio/                #     知识库与检索演练
│   │   │   ├── skills-tools/              #     技能与 MCP 工具市场
│   │   │   ├── evals/                     #     评测与 Prompt 实验
│   │   │   ├── billing/                   #     计量计费与配额
│   │   │   ├── guardrails/                #     安全合规与围栏
│   │   │   └── system-logs/               #     系统与 LLM 日志
│   │   ├── src/components/{crud,layout}/  #   统一 CRUD 套件 + 布局壳
│   │   └── src/{hooks,lib,store}/ · e2e/ · tests/
│   ├── web/                               # 轻量客服端 (Port 3000)
│   │   ├── src/components/                #   聊天 UI(含 audit/ 审计卡片)
│   │   └── src/{pages,hooks,lib}/ · components/ · e2e/{fixtures,helpers}/ · tests/ · public/uploads/
│   ├── merchant/                          # 商城消费者端 (Port 3005)
│   │   ├── src/components/{chat,orders,address,navbar}/
│   │   └── src/{pages,context,lib}/ · e2e/
│   └── merchant-admin/ ⭐                 # 商户独立后台 (Port 3006, 按菜单域组织)
│       ├── src/pages/                     #   每域一目录(多数带 components/)
│       │   ├── analytics/                 #     数据分析全屏工作台(悬浮助手/ResultCard/信任章)
│       │   ├── board/                     #     数据看板
│       │   ├── reports/                   #     我的报告(CSV 导出)
│       │   ├── order-manager/             #     订单工作台(orders/approvals/live-desk/spi-logs 四 tab)
│       │   ├── goods/{products,skus}/     #     商品 CRUD + SKU 库存
│       │   ├── customers/                 #     客户管理
│       │   ├── promotions/                #     优惠活动 CRUD+核销
│       │   ├── live-desk/                 #     客服/坐席工作台
│       │   ├── login/                     #     真实登录(bcrypt+JWT)
│       │   └── system/{menus,roles,staff}/  #  RBAC 三件套
│       └── src/{components,lib,test}/ · e2e/ · public/
│
├── services/                              # Python 后端 (uv workspace)
│   ├── gateway-py/                        # FastAPI 网关 (Port 4000, 134 条端点)
│   │   ├── src/gateway_py/routers/        #   八路由域: analytics/merchant/admin/crud/chat/auth/spi/live_desk
│   │   └── tests/                         #   454 契约测试(事实标准)
│   └── engine-py/                         # LangGraph 决策引擎
│       ├── src/engine_py/
│       │   ├── analytics/                 #   ⭐ data agent 独立轻管线(语义编译/T0·T1·T2 三通道/守卫链/信任章)
│       │   ├── graph/nodes/               #   客服 LangGraph 拓扑(triage→planner→exec⇄val→finish)
│       │   ├── triage/stages/             #   意图分流(分类头缝①)
│       │   ├── skills/{cart,guide}/       #   技能管道 + 确定性兜底分发(LLM 不可达仍真答)
│       │   ├── tools_registry/            #   工具/指标语义注册表(闭集 39 指标 + 语义层事实源)
│       │   │   └── mall/                  #     商户域四簇(cart/catalog/addresses/fulfillment)
│       │   ├── approvals/                 #   HITL 审批 + 事务发件箱
│       │   ├── memory/                    #   四象限记忆 + 双层画像
│       │   ├── rag/                       #   Contextual RAG(混合检索)
│       │   ├── vision/                    #   多模态视觉消歧
│       │   ├── {llm,cards,badcase,db,evals}/  #  LLM 接入/卡片家族/坏例池/DB 模型/离线评测
│       │   └── intent_flywheel/           #   ⭐ 意图数据飞轮 CLI(七件)
│       ├── alembic/versions/              #   DB 迁移
│       ├── evals/                         #   意图评测语料(572 句)
│       ├── tests/                         #   1834 测试
│       ├── scripts/training/{,configs}/   #   小模型训练脚手架
│       └── training_data/{metric_head,sft}/  #  训练数据与产物
│
├── packages/                              # 共享工作区包
│   ├── types/src/                         #   冻结前端契约类型(zod)
│   └── ui/                                #   零组件库依赖共享 UI
│       └── src/components/{ui,chat/cards,approval}/ · src/{hooks,lib,styles}/ · tests/
│
├── eval/                                  # promptfoo 评测
│   ├── prompts/ · providers/ · scorers/ · lib/
│   ├── testCases/{ecommerce,data_analytics,legal,persona,security}/
│   └── {baselines,results}/ · nightly/results/<时间戳>/   #   夜间评测逐轮留档
│
├── e2e/                                   # Playwright 配置(主套件 + 熔断/商户/审计独立配置链式)
├── docs/
│   ├── adr/                               #   架构决策记录(0001-0014)
│   ├── architecture/                      #   深度设计(RAG/HITL/多模态/扩容)
│   ├── specs/ · wayfinder/{mall-data-agent-split,dynamic-analytics}/  #  规格 + 决策票图谱
│   ├── {training,knowledge,agents}/       #   训练文档 / 知识库 / agent 协作规则
│   └── assets/readme/                     #   README 截图(四终端实览)
├── deploy/                                # 部署物: {k8s,lb,monitoring,embedding}/(K8s 清单/负载均衡/监控/TEI)
├── scripts/                               # 仓库级工具脚本(含 debug/)
├── public/uploads/                        # 运行时上传产物
└── .github/workflows/                     # CI
```

---

## 🔌 核心基础设施 (Platform Core)

以下平台核心能力自 v3 起稳定，深度设计详见 `docs/architecture/` 与对应 ADR：

- **客服 Agent 决策图**：triage(意图分流+咨询直答快轨) → planner(规划/快轨) → executor ⇄ validator → finish；确定性兜底分发器（LLM 不可达时优惠/券/订单状态仍真答）。
- **HITL 审批**：ApprovalGatekeeper（双退款/阈值/高额改址拦截）+ 事务发件箱（审批状态与 outbox 事件同事务原子提交）+ 同步 Fast-Path 恢复（确定性 JobId 派发 run_agent 续跑）+ Outbox 对账 Worker（`FOR UPDATE SKIP LOCKED`；周期任务由 scheduler 随 gateway lifespan 调度，[ADR-0007](docs/adr/0007-temporal-execution-route-retired.md) Temporal 路线已退役）。
- **四层记忆**：short/long/episodic/task（AgentMemoryEngine 统一收集与落盘）。
- **Contextual RAG**：BM25+向量+RRF 混合检索，知识文件自愈补灌。
- **参数化 SQL 沙箱**：sqlglot AST 只读审计 + `READ ONLY` 事务 + 超时熔断 + `LIMIT` 约束；租户边界由服务端模板注入 + 编译层断言（谓词不可剥离，`require_business_id`）。
- **多租户隔离**：business_id 强制过滤、PII 递归脱敏、SQL 下推隔离。
- **实时协同**：Redis Streams 事件主干 + Last-Event-ID SSE 回放 + socket.io 坐席接管。
- **开放 SPI**：HMAC-SHA256 签名 + 防重放，对接商户私有 ERP/WMS。

---

## 🧪 测试 (Testing, 全量绿)

| 套件 | 数量 | 覆盖 |
|---|---|---|
| engine pytest | **1834** | 意图仲裁/视觉消歧/记忆/优惠引擎/golden SQL/兜底分发器/RBAC/报告/数据水龙头/训练流水线/data agent 管线；2.7.0 新增语义编译器差分对拍/组合通道/探索守卫/归因速览/语感直通契约册 |
| gateway pytest | **454** | HTTP/SSE/socket.io 契约 + analytics 路由 43 条 93 例(ask SSE/反馈/RBAC/报告/核销幂等) |
| merchant-admin vitest | **251** | ResultCard 渲染(信任章/generatedSql 折叠/叙事隔离区)/FloatingAgent/菜单树/SKU 库存/客户抽屉/活动范围/page-context/答案反馈 |
| merchant-admin E2E | **11** | 登录门卫/RBAC 菜单/六胶囊真答/悬浮 agent/报告/优惠 CRUD |
| promptfoo | 就绪 | 统一意图册 58(槽位程序生成+T2 型长尾) / planner 8 / persona 8 / T1·T2 通道十轮守卫基线 — 需模型代理在线 |

```bash
bun run test:engine        # engine 全量 (1834)
bun run test:eval          # gateway 全量 (454)
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

bun run dev:all                           # 四前端(turbo): web 3000 / admin 3001 / merchant 3005 / merchant-admin 3006
bun run dev:server                        # FastAPI 网关 (Port 4000, uvicorn --reload)
```

| 服务 | 地址 | 说明 |
|---|---|---|
| apps/web | :3000 | 轻量客服端(登录 test@example.com / agent-all-dev) |
| apps/admin | :3001 | SaaS 控制平面(免登录演示视角) |
| apps/merchant | :3005 | 商城消费者端(真实登录，演示账号一键切换) |
| **apps/merchant-admin** | **:3006** | **商户后台(数据分析/优惠/RBAC，老板账号 test@example.com)** |
| gateway-py | :4000 | FastAPI 网关(134 条端点) |

> **灰度开关**（分层信任三通道）：`AI_T1_COMPOSE=on` 开 T1 组合通道；`AI_T2_EXPLORE=on` 且 admin/finance_owner 身份开 T2 探索；`AI_ATTR_NARRATIVE=on` 开归因叙事（默认关）。周期任务（审批对账/坏例池摘要）由 scheduler 随 gateway lifespan 自动启动，单实例假设；`ENGINE_SCHEDULER_ENABLED=0` 可整体关闭，多实例部署见 [扩容指南](docs/architecture/multi-instance-deployment.md)。

---

## 📚 深度文档 (Deep Docs)

| 文档 | 内容 |
|---|---|
| [ADR-0010](docs/adr/0010-tiered-trust-architecture.md) | **分层信任架构**（T0 核验/T1 组合/T2 探索三通道 + 语义层单一事实源） |
| [ADR-0011](docs/adr/0011-attribution-phase-b-boundary.md) | 归因增强边界（贡献度分解 B1 + AI 叙事隔离章 B2） |
| [ADR-0004](docs/adr/0004-semantic-layer-route-and-dual-agent-seam.md) | 语义层路线(LLM 永不写 SQL)+双 Agent 模块缝 |
| [ADR-0005](docs/adr/0005-data-agent-llm-intent-and-growth-loop.md) | L3 LLM 意图兜底 + 覆盖增长机制(未命中落库) |
| [ADR-0006](docs/adr/0006-data-agent-architecture-comparison.md) | **架构对照:LangGraph+MetaRAG+GRPO 全家桶提案 vs 语义层轻管线**——逐层采用/暂不采用/明确不采用的理由与重新评估触发器 |
| [训练文档](docs/training/metric-head-training.md) | 小模型数据源/格式/库/参数/部署全链路 |
| [商户接入指南](docs/merchant-onboarding-guide.md) | SPI 对接/RAG 灌入/审批策略 |
| [架构深度指南](docs/architecture/) | RAG/HITL 重规划/弹性部署/多实例扩容 |
| **[生产部署方案](docs/deploy.md)** | **Docker Compose 全栈上线:四前端 nginx 一体/gateway/PG/Redis,五步上线+运维+安全清单** |
| [CHANGELOG](CHANGELOG.md) | 版本明细（2.7.0 = v4.1；2.6.x 日粒度演进持续回填） |

---

## 📄 历史版本

- **v3.2 / v3.1 / v3 / v2 / v1**：见 [CHANGELOG.md](CHANGELOG.md) 与 git tag（v1 在分支 `v1-main`）。
