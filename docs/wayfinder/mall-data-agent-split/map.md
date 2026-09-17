# Wayfinder Map: 商城 agent 与商户 data agent 双模块重构

Label: wayfinder:map

## Destination

一份可交接的重构 spec（**2026-09-18 用户重画扩大**：从「两 agent 重构」扩展为「完整商户后台系统」），包含四部分：①商城 agent 与商户 data agent 的模块缝与接口定义（商城侧仅边界收口）；②商户 data agent 的技术路线决议（口语→SQL 编译路线、schema 获取、口语→领域概念映射、SQL 动态拼接与安全、查询缓存策略）+ 首版能力清单与卡片形态；③小模型使用/训练决策文档与数据方案（含本图内落码的最小数据水龙头）；④**merchant-admin 后台系统模块规划**——全局悬浮 agent（全路由可用、上下文感知）、模块化菜单（商品/分类/订单/用户/权限管理/运营管理）、实体对比能力、运营管理（优惠活动）模块。

## Notes

- 本图物理位置：`docs/wayfinder/mall-data-agent-split/`（2026-09-17 用户决议迁入 docs/ 随 git 版本控制留档；偏离 issue-tracker.md 的 .scratch 默认约定，wayfinder 的 map/tickets/frontier 查询按本目录执行）。
- **2026-09-18 用户重画（产品形态追加决议）**：①agent 入口改为**全局悬浮**（后台任意路由可用，上下文=当前路由+选中数据，参照 storefront FloatingChatWidget 模式；数据分析页保留为全屏对话形态）；②后台菜单按模块分：**商品、分类、订单、用户、权限管理、运营管理（优惠活动）+ 数据分析/我的报告**，每模块自带子菜单与路由；③**实体对比进 v1**（选中商品/订单对比——经实体 IN 过滤 + GROUP BY 实体的对比卡片实现，单次查询不违反 15-D1 单轮决议；时间对比/环比仍二期，10-D5 时间对比部分不翻案）；④运营管理（优惠活动）为**写操作业务模块**，与 data agent 只读边界分开，规划进 20 号票。
- 域：smartServe-agent v3 —— FastAPI 网关（services/gateway-py）+ LangGraph 决策引擎（services/engine-py）。商户工作台在 apps/merchant/admin（当前无任何数据看板）。
- 图谱期已定决策（2026-09-17 与用户对谈定案，后续票不得翻案，除非目的地重画）：
  - 驱动力：新增商户数据能力为主，意图质量为辅；
  - 终点形态：可交接 spec，非直接改代码——唯一例外是最小数据水龙头（07 号票落码，因数据积累靠日历时间）；
  - 物理形态：先逻辑拆分，部署拆两个服务不在本图；
  - data agent：仅商户侧入口（apps/merchant/admin），对话式 + 富卡片起步，预留固化报表演化；首版严格只读（DB 只读角色 + business_id 强制过滤）；
  - 商城 agent：仅边界收口，不深改（triage/skills 刚经历 Stage 化/contract 化重构，不再翻搅）；
  - 小模型：必须出结论，但数据可行性先行。**2026-09-17 追加常设决议：暂不训练，spec 预留三个插入缝（意图分类头 / 指标映射分类头 / 判重缓存换模），统一「接口冻结、模型即 adapter」模式；训练由用户日后自行完成再接入，触发条件与缝契约见 11 号票。**
- 关键仓库事实（图谱期探查已核实）：
  - `services/engine-py/src/engine_py/tools_registry/metric_registry.py`（词表/同义词/conflictGroup 消歧/sqlTemplate）已从 v2 移植但**无运行时消费者**；
  - `tools_registry/order_domain.py` 的 `query_product_ranking` 是唯一运行时统计工具（手写 SQL 聚合商户真单，gmv/volume/gross_profit/margin_rate/stock_risk 五口径）；
  - v2 NL2SQL 引擎（NLMetricQueryEngine）未移植，规格存于 `docs/specs/production-resiliency-and-multi-tenant-safety.md`；
  - 数据面：商户物理库 agent_merchant（merchant_orders / merchant_order_items 含成本快照 / merchant_product_reviews，DDL 在 `services/gateway-py/src/gateway_py/merchant_db.py`）；engine 本地 36 表（`db/models.py`）含 product_reviews / after_sale_tickets / session_metrics / intent_logs / low_confidence_logs；销量无独立表靠聚合；
  - 意图判定为三层仲裁：规则白名单 → embedding 锚点（BAAI/bge-small-zh-v1.5，29 锚句）→ LLM 结构化精判（AI_MODEL 默认 gemini-3.5-flash），另有 intent_exemplars 租户示例向量召回；**无任何微调基建**；
  - 评测资产：promptfoo 评测集 55 条（18 条带意图断言），无独立标注训练集，badcase 池为运行时 DB 表且仓库内零原始数据。
- HITL 票用 grilling 技能主持；涉及模块/缝/接口的表述用 codebase-design 词汇（module / interface / seam / adapter / depth）。
- research 票由 general-purpose 子代理直接执行（本环境无独立 research 技能）：答案写入票文件 `## Answer` 并置 Status: resolved；不建 throwaway 分支（工作树有未提交改动且多会话并行）；**map.md 的 Decisions-so-far 指针由主会话在收到完成通知后统一追加，子代理不得并发写 map.md**。
- 工程规范：Python 侧 uv + pytest + ruff（落码票遵守）。
- 参照项目：[spring-ai-alibaba/DataAgent](https://github.com/spring-ai-alibaba/DataAgent)（Apache-2.0，2.7k★，Java/Nuxt 栈）——企业级数据分析 agent（StateGraph NL2SQL + Python 沙箱深度分析 + ECharts HTML/MD 报告 + MCP + 多模型注册表 + 规划 HITL）。**不引码**（栈不同），仅作产品与架构参照（报告形态 / 沙箱演化缝 / 编排），见 14/15 号票；其权限模型仅 API Key 细粒度、无多租户行级设计，参考价值低（13 号票自行设计）；其「超越 text-to-SQL」的自由生成定位与 08 号已锁路线（LLM 永不写 SQL）相悖，不作路线范本。

## Decisions so far

- [12 重构 spec 汇编](../../specs/mall-data-agent-split.md)：spec 已发布（docs/specs/mall-data-agent-split.md，ready-for-agent，含 30 条 user story + 六阶段实现排期）；ADR-0004 蒸馏 08/09 架构决议；汇编期用户追加三层 RBAC（菜单/按钮/指标）与快捷切换账号并入 spec；无决议冲突。**20/20 票 resolved，目的地抵达（2026-09-18）。**

- [16 merchant-admin 产品原型定稿](issues/16-product-prototype.md)：全局悬浮 agent（上下文=路由+选中联动）+ 数据分析全屏工作台（与悬浮共享会话线程）+ 模块化菜单（数据/商品/订单/用户/运营/系统）+ 实体对比 v1（并排表+雷达图多卡，闭集维度随权限过滤）+ 报告统一进我的报告；资产=prototype/index.html。
- [20 运营管理（优惠活动）模块规划](issues/20-promotions-module.md)：规划进 spec、实现排 data agent 之后；数据模型草案=promotions + promotion_redemptions（17 号迁移流程）；结算应用优惠=资金口径改动独立实现票；活动效果指标族待数据落库后登记；界面=CRUD+审计（merchant_audit_logs）。

- [03 口语→领域概念映射层研究](issues/03-colloquial-mapping-research.md)：现有 metric_registry 只管得住正向词典核口语，未命中会静默兜底 gmv（数据诚实隐患，消费前必修）；建议四层映射——L0 同义词归一 / L1 指标口径（registry 单一真源 + 口径文档单向生成入 RAG）/ L2 查询示例（扩 intent_exemplars 双池）/ L3 LLM 兜底反问；小模型适合形态是 L0–L3 间的 closed-set 归一分类器（弱标注可由词表自动造）。
- [02 schema 知识获取方案研究](issues/02-schema-knowledge-research.md)：初步倾向 B（代码静态事实源生成 schema 卡片）为主体；A（运行时 introspection）缩限为启动期/CI 漂移检测断言（gateway sqlglot 沙箱本就禁 information_schema）；C（DDL 入 RAG）让位给口径白话文档——500 字符切块会斩断 CREATE TABLE，检索漏检即错 SQL。新事实：商户库是单份幂等 DDL 只增不删改（漂移隐患）；口径双轨制——metric_registry sqlTemplate 硬编码 engine 本地表而 queryProductRanking 手写 SQL 打商户库，08 号拍板必须对齐。
- [05 小模型最佳落点研究](issues/05-small-model-placement-research.md)：优先级 ① 指标映射分类头（150-400 句标注、CPU 分钟级训练，消灭已立案的「利润榜变销量榜」口径错答）② 锚点层升级为全 15 意图分类头 + 三段路由（0.5k-3k 句，可分流 40-70% LLM 调用）③ 判重缓存先做每租户阈值校准（零训练），bge 微调缓行 ④ 替换 LLM 精判层不推荐（单次调用兼做分类+槽位+编排，纯分类头接不住）⑤ badcase 分池复用①产物。管线事实修正：锚点层现仅覆盖 3/15 意图；MetricSemanticResolver 只接了 eval provider 未进运行时；共同阻塞项是标注数据闭环与 eval 扩容。
- [01 口语→SQL 编译路线对比研究](issues/01-nl2sql-route-research.md)：三路线事实对比已成（A 语义层 / B LLM 动态生成 / C 混合）。业界基准：语义层范围内准确率 ~100% vs text-to-SQL 51-62.5%，且范围外前者明显失败、后者静默错答（数据诚实铁律倾向 A/C）。代码事实：metric_registry 的 render_sql 用裸 str.replace 无绑定参数（v2 规范 §3 明示的注入面）；指标定义现有 3 份漂移副本（registry / order_domain 私有 METRIC_REGISTRY / 模板）；query_product_ranking 无时间窗支持（Phase 1b TODO）；v2 规格已含与路线无关的沙箱基线（位置参数 + READ ONLY + 3s 超时 + 50 行上限）。
- [04 SQL 动态拼接与安全执行研究](issues/04-sql-safety-research.md)：四层校验链成案——解析层 sqlglot parse + AST 白名单（sqlglot 30.18.0 MIT 高频维护可选；pglast 8.4 GPL-3.0 需法务；sqlparse 自述 non-validating 不可作安全边界；asyncpg 无参 execute 走 simple 协议允许多语句，必须全程带参）、编译层 CompiledSQL 参数化 + 租户谓词服务端注入不可覆盖 + LIMIT clamp 1-50、DB 层只读角色 + 独立连接池 + statement_timeout 3s + EXPLAIN 预算（对齐 v2 规格）、呈现层分类诚实报错。前置工程雷：_merchant_reader_engine 读写共用同一引擎（UPDATE 同引擎跑），落地只读池前必须拆读写。
- [08 data agent 技术路线拍板](issues/08-tech-route-decision.md)：主路线 = C 收敛变体——指标模板为唯一执行通道（fragment 闭集 + bindparams + v2 §3 沙箱），LLM 只做语义解析永不写 SQL，未建模响亮失败+反问，text-to-SQL 兜底不做（留二期缝）；schema = 编译期静态卡片，introspection 缩为漂移断言，RAG 只放口径文档；映射 = L0-L3 四层 + query_exemplars 新表双池 + 口径文档 registry 单向生成；SQL 链 = sqlglot 四层校验全采纳（pglast/sqlparse 否决），先拆 _merchant_reader_engine 读写；存储 = SQL 不入 RAG，语义缓存按计划指纹 + 示例回流 + 口径指纹失效。公共前提：废静默兜底 gmv、指标定义收敛单一事实源。
- [09 模块缝划定](issues/09-module-seam-decision.md)：data agent 独立轻管线（不进 triage，engine 内两图并行）；鉴权挂商户员工面新路由组 /api/admin/analytics/*（底层复用 threads/messages/SSE，不混 C 端 /api/chat）；归属表——共享会话/推送/卡片约定，商城专属 triage/深层记忆/审批/ecommerce 工具，data 专属 L0-L3 + 编译器 + 沙箱（落点 engine_py/analytics/）；商城侧收口仅三件（注册表收敛并退役私有副本、PROFIT_RANKING_RE 一处删除、query_product_ranking 换底层保工具面）；MetricQueryEngine 三方法 interface + 四错误模式 + 两不变量入 spec。
- [10 首版能力清单与卡片形态](issues/10-first-version-scope.md)：四族做薄——销售排行族（现有 5 指标+反向方向+时间窗+品类过滤）、评价族（差评榜/评分分布，merchant_product_reviews）、退货退款族（退款率/退款金额/售后工单分布）、会话客服族（会话量/自动解决率，session_metrics 同源）；卡片表格为基座+折线/条形两类图，图表库定 ECharts；六快捷胶囊；口径骨架表入 spec；不做对比/归因/跨实体多跳/导出（导出归 14 号）。新指标注册顺序：评价→退货→会话。
- [07 最小数据水龙头落码](issues/07-data-tap-task.md)：已交付 scripts/export_intent_data.py（--source intent|low_confidence|badcase + 时间窗 → JSONL）+ 15 测试全绿、ruff 干净、零 schema 改动；真实库实测 intent_logs 1966 行（两周）/low_confidence 4/badcase 547（intent_conflict 504 为主）。缺口事实：actual_outcome 无写入方恒空、low_confidence 表缺 intent/confidence 列（导出经 candidates[0] 推导）、intent/low_confidence 无 TTL（badcase 有 90d/30d 保留）。
- [06 意图标注数据可行性](issues/06-intent-data-feasibility.md)：去重是决定性事实——1966 行仅 270 唯一句（86% 重复，评测重跑为主），有机速率 5-10 唯一句/天。时间线：指标映射头（150-400 句）数天-2 周可训、不必等积累；意图头 0.5k 档被动 1-2 个月/主动数周；3k 档被动 5-16 个月、必须 LLM 扩写+生产流量。badcase 的 suggested_class 恒为 neutral 不可直接作弱标注，但 97.6% 可经 thread_id 回联原文，去重后 71 个唯一难题句=人工约一小时可清的辅助标注队列（须在 90 天 TTL 内消化）。标注主通道=LLM 预标+人工只裁分歧；55 条评测集冻结为纯门不入训（实测 28 条带 expectedIntents）。隔离五条与触发条件（唯一句 ≥500 且每意图 ≥32、合成占比 ≤50%；连续 2 月增速 <300/月转主动造数；冲突句/周连升 2 周为漂移重训信号）已备，供 11 号直接引用。
- [19 merchant-admin 独立后台应用](issues/19-merchant-admin-app.md)：拆分 apps/merchant-admin（六 tab 平移不重写，storefront 删 /admin，analytics 落新家）；技术栈强制 = 与 apps/merchant 同栈（Bun+Vite 6+React 19+TS）+ **组件库强制 packages/ui**（禁本地造重复组件/第二套组件库）+ ECharts；**PageContext 契约**——前端随消息上行 route/tab+选中实体 ids+活动过滤，作为 resolve 的 session_ctx 一部分，选中实体走模板实体过滤 fragment（IN 绑定参数，business_id 服务端重校验，v1 单一上下文源）；菜单 IA 四分组（数据/运营/客服/配置）方向定稿交 16 号（已扩题含 PageContext 交互原型）。
- [15 data agent 内部执行编排](issues/15-execution-orchestration.md)：轻量单轮小图（intake 含 PageContext → resolve L0-L3 → 反问分支|compile→execute → 卡片 → SSE），不接 StepExecutionEngine/审批引擎/planner 快轨（只读分析用不上，商城 step 体系不动）；v1 无多步无计划态（引导靠反问与胶囊，演化缝=data agent 专属轻计划态）；零 HITL；Python 沙箱深度分析列二期评估项（打破「LLM 永不产出执行代码」铁律须独立评估，触发=整理计算类长尾经验证成规模）。
- [11 小模型决策文档](issues/11-small-model-decision.md)：三缝冻结入 spec——IntentScorer（意图头）/ 指标映射 adapter / 缓存换模位，统一「问句→闭集标签+置信度、模型即 adapter」；触发条件建议值：指标头随时可启动（150-400 句几天攒够）、意图头 ≥500 唯一句且每意图 ≥32 合成 ≤50% + 冲突队列清零、漂移=冲突句/周连升两周、每月导出统计例程；训练模板 = SetFit 式线性头/bge 微调 + 四步数据加工 + 近邻过滤隔离；接入 = 影子跑 → intentF1 达标 → 配置切换，回滚 = 配置回退，LLM 保留最终仲裁。
- [13 数据权限与配额](issues/13-data-permission-decision.md)：角色=接线 permissionTag 三档（finance_owner 老板全量 / sales_viewer 运营不见成本 / warehouse_operator 仓储），默认全员 finance_owner 起步，角色 UI 落设置区；指标级=毛利/毛利率/库存风险限 finance_owner，registry 登记必须带 tag；行级 v1 不做（预留编译层谓词缝）；执行位置=编译层过滤 metric 闭集 + 反问选项集同步过滤 + 卡片兜底；配额=v1 复用 LLM token 计量 + 网关层每员工每分钟查询限流，独立计费二期。
- [17 schema 漂移检测与商户库迁移](issues/17-schema-drift-mechanism.md)：双层断言——CI 期强断言（临时 postgres 重放 DDL+alembic 后 inspect 对比代码事实源，不一致即红）+ 启动期轻检查（真实库 inspect vs 卡片指纹，防手工改库）；商户库 v1 不上 alembic（删列/改型走显式迁移 SQL 入仓 + 同步 DDL 字符串 + CI 护栏，alembic 二期触发=频繁演化/多部署）；失败分面容错——核心链路只告警不阻塞，分析面主动降级诚实拒绝；卡片生成器与断言器解耦（共享事实源定义）。
- [18 data agent 评测面](issues/18-eval-surface.md)：新建 dataMapping scorer（四要素：指标/维度/方向/时间窗，provider 直调 resolve）+ eval/testCases/data_analytics/ 新族（六胶囊原句+每族 15-30 句+反问/不支持案例=08-P1 回归门）；golden SQL 双冻结（销售族从 query_product_ranking 现行为冻结，新族实现时交付，复用 17 号 CI 种子库）；两者进 CI 必须绿；隔离写成单条不变量——评测集纯门永不入训 + 训练近邻过滤 cos≥0.90。
- [14 报告生成与导出](issues/14-report-generation.md)：v1 = 即席卡片 + 手动生成报告（定时订阅推送二期，触发=真实使用频率）；格式 = 表格 CSV 导出 + 单页 HTML 报告（ECharts+指标表+结论段，数据同源 MetricQueryEngine 不另起管线）；**不变量：数字全部来自真实查询，LLM 只写结论文字并标注口径，禁止编造数字**；存储 = analytics_reports 新表 + uploads 通道，「我的报告」列表页；入口 = 结果卡动作按钮 + 对话指令，六胶囊保持即席。

## Not yet specified

（无——全部决议或票化；灰度/回滚已由 11-D4 覆盖）

## Out of scope

- 平台侧 apps/admin 全局分析（大盘已存在，session_metrics 库内真算）——图谱期决议。
- 拖拽式 BI 报表编辑器——图谱期决议。
- data agent 写操作与动作执行（批量回复差评、打标等，涉 HITL 审批闸）——首版只读，二期另起 effort。
- 商城 agent 深度重组——图谱期决议。
- 部署拆分为两个独立服务——先逻辑后物理。
- 大模型（LLM 本体）微调——沿用 `docs/specs/admin-console-operational-readiness.md` 既有 out-of-scope 决议；本图只议小模型。
- 完整标注界面与训练管线建设——图谱期决议仅落最小水龙头。
