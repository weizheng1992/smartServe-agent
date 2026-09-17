# 09: 商城 agent ↔ data agent 模块缝划定

Type: grilling
Status: resolved
Blocked by: 05, 08

## Question

HITL 设计会话（用 codebase-design 词汇：module / interface / seam / adapter / depth）：划定两个 agent 的模块缝——

- data agent 入口挂接：复用现有 chat 管线（threads / messages / SSE，新 agent 类型路由）vs 独立轻管线（不走 triage 全 Stage 链）；
- 共享基建清单与归属：triage Stage 骨架、四层记忆（AgentMemoryEngine）、审批闸（首版只读用不到，预留缝）、卡片组装（CardSynthesizer）、工具注册（tools_registry）——哪些是平台共享模块（interface 留给两个 adapter），哪些是商城专属；
- 商城侧需要的边界收口项（图谱期决议：只收口不深改，列出最小改动清单）；
- data agent 的 SQL 执行器作为深模块的 interface 草案（方法面、错误模式、租户约束）。

产出：缝清单 + 每条缝的 interface 归属表，进 spec 第①部分。

## Answer

决议日期 2026-09-17，用户全盘采纳推荐（Q1–Q5）。

### D1 管线形态 = 独立轻管线

data agent **不进** 9-Stage triage 链（triage 是 C 端客服意图域：订单/退款/物流槽位、资金闸、重复拦截；商户分析是指标/口径/时间窗域，硬塞会两域纠缠）。engine 内两图并行：商城 agent 图（现状不动）+ data agent 图（L0–L3 映射 → 查询编译 → 卡片组装）。

### D2 会话与鉴权 = 商户员工面新路由组

- gateway 商户运营鉴权面（merchant.py 的 `/api/admin/*`）下新增 `/api/admin/analytics/*` 路由组；**不混入** C 端 `/api/chat`（员工与消费者是两个鉴权域，线程归属也会混）。
- 底层复用 threads / messages / SSE 推送基建——省存储与推送，分开的只是入口与鉴权；分析会话归属商户员工用户。

### D3 共享基建归属表

- **平台共享**：threads/messages/SSE、限流熔断、观测埋点、卡片组装约定（quick_replies 单胶囊、死按钮禁令、诚实空态）。
- **商城专属**（data agent 不碰）：triage Stage 链、task/episodic/long 记忆（首版不接，留缝）、审批闸（只读用不到，缝在执行引擎插入位预留）、ecommerce_tools 工具族。
- **data agent 专属**（商城侧不碰）：L0–L3 映射管线、metric_registry 运行时化改造、查询编译器 + SQL 沙箱执行器、query_exemplars、分析卡片类型。落点：`engine_py/analytics/` 新子包（图谱期已决先逻辑后物理，不起新服务）。

### D4 商城侧最小收口清单（仅三件，其余一行不动）

1. metric_registry 收敛单一事实源 + order_domain 私有 METRIC_REGISTRY 退役（落实 08-P2）；
2. `PROFIT_RANKING_RE` 收编进 L0：triage 侧一处删除，不重构；
3. `query_product_ranking` 底层换到新查询执行器，工具面（planner 快轨 + 工具 schema）零变化——商城 agent 行为完全不变。

### D5 MetricQueryEngine 深模块 interface 草案（采纳，入 spec）

- `resolve(question, session_ctx)` → StructuredQueryIntent | ClarificationRequest（反问）
- `compile(intent, session_ctx)` → CompiledSQL（租户谓词已注入、LIMIT 已 clamp、AST 已断言）
- `execute(compiled)` → QueryResult（rows + 指标元数据 + 口径注记）
- 错误模式契约：不支持→响亮失败+可选问法；歧义→反问（conflictGroup 为选项集）；超预算/超时→如实报告；无数据→诚实空。
- 不变量：用户输入永不进 SQL 文本；business_id 永不被调用方触达。
- 实现期自由度：内部 staging、缓存挂点（08-D5 语义缓存）、连接池细节。
