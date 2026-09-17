# 商城 agent 与商户 data agent 双模块重构（含 merchant-admin 后台系统）

- 日期: 2026-09-18
- 状态: **ready-for-agent**
- 来源: wayfinder 图 `docs/wayfinder/mall-data-agent-split/`（20 张决策票全部 resolved，本 spec 为其汇编；细节决议以各票 Answer 为准，冲突回票重议）
- 关联: ADR-0004（data agent 技术路线与双 agent 模块缝）；可交互原型 `docs/wayfinder/mall-data-agent-split/prototype/index.html`；数据水龙头 CLI 已落码（见 Further Notes）

## Problem Statement

商户经营者（老板/运营/仓储）今天没有任何数据分析能力：后台只有订单发货、退款审批、客服工作台等事务性 tab，没有看板，也没有地方问「上个月卖得最差的是谁」「差评最多的 SKU」「近 30 天退款率」。想看数据只能找开发跑 SQL。同时这些事务功能平铺在 C 端商城应用的一个路由下，员工工具与消费者界面同 bundle、同发布节奏。意图判定层面，现有三层混合管线的 embedding 锚点只覆盖 3/15 意图、口径映射存在已立案的「利润榜答成销量榜」错答，且系统没有任何微调基建与训练数据积累。

## Solution

一次重构交付三件事：

1. **商户 data agent**：只读、对话式的数据分析 agent——商户后台任意页面全局悬浮可唤起（上下文=当前路由+选中数据），也可进入全屏工作台深聊；口语问题经 L0-L3 映射层解析为结构化查询意图，由指标模板确定性地编译执行（**LLM 永不写 SQL**），失败响亮、数据诚实。
2. **merchant-admin 独立后台应用**：员工工具从商城应用中拆出，模块化菜单（数据/商品/订单/用户/运营/系统），三层 RBAC（菜单/按钮/指标）+ 顶栏快捷切换账号，实体对比、报告生成、优惠活动（规划落地）。
3. **小模型接入缝**：暂不训练，但三个插入缝（意图分类头/指标映射分类头/判重缓存换模）契约冻结，训练数据水龙头已开始积累。

商城 agent（现有 C 端客服）保持不动，仅做三件边界收口。

## User Stories

1. As a 商户老板, I want 在后台任何页面点开悬浮助手问「本月销量 Top10」, so that 不用找开发跑 SQL 就能掌握经营状况
2. As a 商户老板, I want 问「上个月卖得最差的商品」时被反问「指销售额还是销量」, so that 不会被含糊问题给出错误答案
3. As a 商户老板, I want 问「为什么退货变多」时得到诚实的「暂不支持」并给出可问的替代问题, so that 不会被 AI 编造的归因误导决策
4. As a 商户老板, I want 勾选 2 个商品点「对比」看到并排指标表和雷达图, so that 一眼看出哪个商品差评率异常
5. As a 商户老板, I want 勾选多笔订单对比金额/状态/物流时效, so that 快速定位履约异常单
6. As a 商户老板, I want 对当前分析一键「生成报告」得到含图表和 AI 结论的单页 HTML 报告, so that 月度经营复盘有可直接分享的材料
7. As a 商户老板, I want 在「我的报告」列表查看和下载历史报告, so that 随时复看不必重新提问
8. As a 商户老板, I want 报告里的 AI 结论标注口径来源且数字全部来自真实查询, so that 报告可审计、敢拿去用
9. As a 商户老板, I want 顶栏快捷切换到运营/仓储账号, so that 预览员工实际看到的菜单和数据范围
10. As a 商户运营, I want 看到销售/评价/售后/会话指标但看不到毛利/成本, so that 数据敏感度按角色隔离
11. As a 商户运营, I want 问毛利相关问题时连反问选项都不出现越权指标, so that 权限边界自然融入对话而非生硬报错
12. As a 商户运营, I want 在订单页选中 3 笔订单直接问「平均金额和状态分布」, so that 页面数据直接进入分析不用重新描述
13. As a 商户运营, I want 快捷问题胶囊一点即答, so that 高频问题零输入成本
14. As a 商户运营, I want 管理优惠活动（满减/折扣/券）的新建/编辑/停用, so that 灵活做促销
15. As a 商户运营, I want 查看活动的 GMV 和核销率, so that 知道活动有没有效果
16. As a 商户仓储, I want 只看到库存/物流相关的菜单和指标, so that 界面不被无关信息干扰
17. As a 商户员工, I want 在后台任意路由唤起悬浮助手且它知道我在哪个页面选了什么, so that 提问不用带上下文背景
18. As a 商户员工, I want 悬浮聊到一半点「全屏对话」继续深入, so that 快问与深聊无缝衔接
19. As a 平台管理员, I want data agent 的所有查询被 business_id 强制隔离且只读, so that 多租户数据绝不越界
20. As a 平台管理员, I want 每员工每分钟查询限流和 LLM token 计量, so that 资源滥用可控可计费
21. As a 平台管理员, I want schema 漂移时分析面主动降级而核心业务只告警, so that 数据结构变更不挡商户做生意也不出错数
22. As a developer, I want data agent 是 engine 内独立轻管线不与 triage 纠缠, so that 两个意图域各自演进互不拖累
23. As a developer, I want MetricQueryEngine 是深模块（resolve/compile/execute 三方法）, so that 安全/缓存/权限的全复杂度藏在接口后面
24. As a developer, I want 商城 agent 的行为在重构后完全不变（工具面零变化）, so that 现有 55 条意图评测与线上行为不回归
25. As a developer, I want 训练好小模型后只写一个新 adapter 加配置切换就接入, so that 模型迭代不改编排
26. As a developer, I want 影子跑对比新旧意图分类器再决定切换, so that 模型升级有量化依据且可回滚
27. As a developer, I want dataMapping 评测与 golden SQL 进 CI 作为合并门, so that 口径回归在合并前被拦下
28. As a developer, I want 意图数据导出 CLI 持续积累标注原料, so that 训练小模型时不用从零攒数据
29. As a developer, I want 商户库 schema 变更走显式迁移 SQL + CI 断言, so that 代码与库不会静默漂移
30. As a 商户老板, I want 后台与商城前端分离各自独立发布, so that 员工工具迭代不影响消费者购物体验

## Implementation Decisions

### 0. 公共前提（先于一切）

- **P1 废除静默兜底**：指标解析未命中与未知指标键一律响亮失败/反问，禁止静默落 GMV（数据诚实铁律）。
- **P2 指标定义收敛单一事实源**：现存 3 份漂移副本收敛回 metric_registry，order_domain 私有注册表退役，模板与商户镜像库对齐。

### 1. 模块边界（商城 agent ↔ data agent ↔ merchant-admin）

- **data agent 独立轻管线**：不进 9-Stage triage 链；engine 内两图并行（商城图不动 + data agent 图：intake 含 PageContext → resolve L0-L3 → 反问分支 | compile → execute → 卡片 → SSE）。
- **落点**：engine 侧新子包 `engine_py/analytics/`；前端新应用 `apps/merchant-admin`（Bun + Vite 6 + React 19 + TS，与 apps/merchant 同栈）；**组件库强制 packages/ui**（禁本地造重复组件、禁第二套组件库；覆盖不了的先进 packages/ui 再用），图表 ECharts（echarts-for-react），样式沿用仓库 Tailwind v4 + shadcn 约定。
- **会话与鉴权**：gateway 商户员工鉴权面下新路由组 `/api/admin/analytics/*`，不混 C 端 `/api/chat`；底层复用 threads/messages/SSE。
- **共享基建归属**：共享=会话/推送/限流/观测/卡片约定；商城专属=triage/深层记忆/审批/ecommerce 工具（data agent 不碰）；data 专属=L0-L3/编译器/沙箱/query_exemplars/分析卡片。
- **商城侧收口仅三件**：①metric_registry 收敛 + 私有注册表退役；②PROFIT_RANKING_RE 收编 L0（triage 一处删除不重构）；③queryProductRanking 底层换新执行器、工具面零变化。
- **编排**：轻量单轮小图；不接 StepExecutionEngine/审批引擎/planner 快轨；v1 无多步无计划态（引导靠反问与胶囊）；零 HITL。
- **PageContext 契约**：前端随每条消息上行 `{route/tab, selection 实体 id 列表, activeFilters}`，作为 resolve 的 session_ctx 一部分；选中实体走模板实体过滤 fragment（IN 绑定参数，business_id 服务端重校验，id 列表设上限）；v1 单一上下文源。

### 2. data agent 技术路线

- **主路线 = 语义层为唯一执行通道**：执行面 100% 指标模板（fragment 闭集 + bindparams + v2 §3 沙箱：位置参数/READ ONLY/3s 超时/50 行上限）；LLM 只做语义解析（问句→结构化查询意图：指标键/维度/方向/实体/时间窗），**永不产出 SQL 文本**；未建模问题响亮失败+反问（conflictGroup 为选项集）；text-to-SQL 兜底不做（留二期演化缝，届时须标注「非核验口径」）。时间窗解析为必补缺口，归 slot 层参数化进模板。
- **schema 获取 = 代码静态事实源**：编译期生成两份 schema 卡片（商户库 7 表全量 + engine 分析面白名单 5-8 表）确定性进解析上下文；运行时 introspection 只做启动期/CI 漂移断言；RAG 通道只放口径白话文档（registry 单向生成，category=metric_glossary，禁手写反向编辑）。
- **口语映射 = L0-L3 四层**：L0 同义词归一（registry 运行时化，补反向词族，收编散正则）→ L1 指标口径（registry 单一真源）→ L2 查询示例 few-shot（**新建 query_exemplars 表**，全局+租户双池，检索复用 exemplar_service 模式）→ L3 LLM 兜底反问。
- **SQL 校验链 = 四层**：解析层 sqlglot（parse + AST 白名单 + qualify 幻觉表列校验 + 函数白名单；pglast/sqlparse 否决）；编译层 CompiledSQL 位置参数 + 租户谓词服务端注入不可覆盖（编译后 AST 断言）+ LIMIT clamp 1-50；DB 层只读角色 + 独立连接池 + statement_timeout 3s + EXPLAIN 预算 + 50 行双保险；呈现层分类诚实报错 + 错误脱敏。asyncpg 全程带参执行。**前置工程项：先拆 _merchant_reader_engine 读写共用引擎再落只读池。**
- **存储 = SQL 不入 RAG 三件套**：语义缓存（问句→已验证结构化查询意图 + SQL 计划指纹，先做每租户阈值校准零训练）；好查询回流 query_exemplars；失效按 registry 口径指纹（时间敏感问句按时间窗指纹）。**不变量：用户输入永不进 SQL 文本；business_id 永不被调用方触达。**
- **MetricQueryEngine 接口（深模块，冻结）**：`resolve(question, session_ctx) → StructuredQueryIntent | ClarificationRequest`；`compile(intent, session_ctx) → CompiledSQL`；`execute(compiled) → QueryResult(rows+指标元数据+口径注记)`。错误模式：不支持→响亮+可选问法；歧义→反问；超预算/超时→如实；无数据→诚实空。
- **首版能力（四族做薄）**：销售排行族（现有 5 指标+反向方向+时间窗+品类过滤）/ 评价族（差评榜 rating≤2、评分分布）/ 退货退款族（退款率、退款金额、售后工单分布）/ 会话客服族（会话量、AI 自动解决率，session_metrics 同源口径）。新指标注册顺序：评价→退货→会话。**实体对比为 v1 能力**（实体 IN 过滤 + GROUP BY 实体，一次回答多卡：并排指标表 + 雷达图；维度=闭集随权限过滤）；时间对比（环比/同比）不做。
- **卡片形态**：表格为主基座，趋势→折线、分布→条形/饼、对比→雷达/分组柱状；六快捷胶囊（本月销量 Top10 / 卖得最差的商品 / 差评最多的 SKU / 近 30 天退款率 / 售后工单概况 / 客服负载概况）。

### 3. 权限与配额（三层 RBAC）

- **角色**：接线 permissionTag 三档——finance_owner 老板（全量）/ sales_viewer 运营（不见成本）/ warehouse_operator 仓储（库存物流面）；员工身份加 role 字段，默认全员 finance_owner 起步，角色管理 UI 落权限管理页。
- **配置粒度三层**：角色 → 可见菜单 + 可见按钮/操作 + 可见指标闭集；执行以服务端为准（编译层过滤 metric 闭集 + 反问选项集同步过滤 + 网关鉴权），前端菜单/按钮隐藏仅为呈现层。
- **RBAC 三件套：菜单管理 + 角色管理 + 员工管理（2026-09-18 用户定案）**：
  - **菜单管理**：菜单树本身是被管理的资源——menus 表（名称/类型=目录|菜单|按钮/路由/图标/排序/状态，business_id 隔离），CRUD 界面；**前端路由与侧栏按菜单配置动态注册渲染**（新增页面 = 注册组件 + 建菜单，不发版即可见）；按钮权限点挂在所属菜单下（如 perms:menu:create）。
  - **角色管理**：角色 CRUD（三默认种子 + 自定义角色）+ **菜单分配权限**——**三级树形勾选（目录 → 菜单 → 按钮权限点）父子联动**，按钮权限点（如 perms:promo:create、perms:order:ship）在树中第三级分配，角色↔菜单含按钮点存 role_menus 多对多；指标权限独立分组（编译层闭集过滤，反问选项集同步）；保存即生效（服务端权威 + 缓存失效），页面内按钮按权限点不渲染（前端呈现层，服务端强制兜底）；变更记 merchant_audit_logs；护栏：老板的系统菜单与系统按钮（菜单/角色/员工管理及其保存权限）不可移除（防锁死），可恢复默认。
  - **员工管理**：员工 CRUD + 员工↔角色分配（staff 表）；顶栏快捷切换账号 = 重新鉴权 + 审计，读取员工列表，老板可预览员工视角。
- **指标级**：毛利/毛利率/库存风险限 finance_owner；registry 登记新指标必须带 permissionTag（评测契约检查）。行级 v1 不做（预留编译层谓词缝）。
- **快捷切换账号**：顶栏账号菜单切换 staff 账号 = 重新鉴权 + 审计记录；可预览其他角色视角。
- **配额**：v1 复用 LLM token 计量（tenant_billing_quotas）；网关层每员工每分钟查询限流（复用滑动窗口）；独立查询计费二期。

### 4. 报告

- v1 = 即席卡片 + 手动生成报告（定时订阅推送二期，触发=真实使用频率）；格式 = 表格 CSV 导出 + 单页 HTML 报告（ECharts+指标表+结论段）；Markdown 不做。
- **不变量：数字全部来自真实查询（同一执行引擎/权限/沙箱批量执行四族指标），LLM 只组织结论语言并标注口径，禁止编造数字。**
- 存储：analytics_reports 新表（business_id/生成者/时间窗/内容引用）+ uploads 通道；「我的报告」列表页；入口 = 结果卡动作按钮 + 对话指令。

### 5. 模型策略（小模型：暂不训练、缝已留）

- **三缝冻结**：①意图分类头——锚点打分段抽 IntentScorer 接口 + 工厂方法，默认实现=现状锚点打分；②指标映射分类头——resolve 前端归一层可替换 adapter，默认 L0+L3；③判重缓存换模——embedding 模型配置位。统一「问句→闭集标签+置信度，模型即 adapter」，回滚=配置回退。
- **触发条件（建议值）**：指标头随时可启动（150-400 句，按实测速率几天-2 周攒够）；意图头 = 唯一标注句 ≥500 且每意图 ≥32（合成 ≤50%）+ 冲突队列人审清零；漂移重训信号 = 冲突句/周连升两周。
- **训练模板**：SetFit 式 embedding+线性头（8 条/类可跑、32-64 稳）；数据加工 = 水龙头导出 → 去重 → LLM 预标双意见 → 人裁分歧 → 近邻过滤（cos≥0.90 防评测泄漏）→ 10-15% held-out。
- **接入**：影子跑（并行打分记日志）→ intentF1 同评测集达标且高于基线 → 配置切换；LLM 精判保留最终仲裁（三段路由）。

### 6. 后台系统（merchant-admin）

- **拆分**：六 tab 平移不重写；storefront 删 /admin 路由；analytics 落新家。
- **菜单 IA（初始种子，菜单管理可动态调整）**：数据（数据分析=全屏工作台 / 我的报告）、商品（列表/分类）、订单（履约）、用户（客户管理）、运营（优惠活动）、系统（菜单管理/角色管理/员工管理）；死按钮禁令适用于每一项。
- **全局悬浮 agent**：任意路由右下角唤起，上下文徽标 = 路由+选中实时联动；与全屏工作台**共享同一条会话线程**。
- **优惠活动（规划进 spec，实现排 data agent 之后）**：数据模型草案 = promotions（类型/有效期/叠加规则/适用范围/状态）+ promotion_redemptions（核销）；结算应用优惠 = 资金口径改动独立实现票（涉 ApprovalGatekeeper 评审）；活动效果指标族（活动 GMV/核销率）待数据落库后登记；界面 = CRUD + merchant_audit_logs 审计。
- **schema 漂移机制**：CI 强断言（临时库重放 DDL+alembic 后 inspect 对比代码事实源）+ 启动期轻检查；商户库 v1 不上 alembic（删列/改型走显式迁移 SQL 入仓+DDL 同步+CI 护栏）；失败分面容错（核心链路只告警，分析面主动降级诚实拒绝）；卡片生成器与断言器解耦。

## Testing Decisions

- **好测试的标准**：只测外部行为不测实现细节；接口即测试面（MetricQueryEngine 三方法是 data agent 的测试缝）。
- **dataMapping 评测**：新建 scorer 断言四要素（指标键/维度/方向/时间窗），provider 直调 resolve；新 testCases 文件族（六胶囊原句 + 每族 15-30 句 + **反问/不支持案例**作为 08-P1 静默兜底的回归门）。
- **golden SQL 双冻结**：每指标族基准 SQL + 种子数据期望结果；销售族从 queryProductRanking 现行为冻结（迁移前后行为不变的证明）；新族实现时同步交付；执行环境 = CI 临时 postgres 种子库。
- **回归门**：dataMapping + golden SQL 进 CI 必须绿（data agent 相关 PR）；现有 55 条意图评测照旧（商城面回归）；L3 LLM 评测沿用 promptfoo provider 模式。
- **隔离不变量**：评测集冻结纯门永不入训；训练启动执行近邻过滤（cos≥0.90）。
- **先例**：意图评测（eval/testCases + intentF1 scorer）、metric_disambiguation 直调 resolver 模式、query_product_ranking 契约测试。

## Out of Scope

- 平台侧 apps/admin 全局分析（大盘已存在）；拖拽式 BI 报表编辑器；定时报告订阅推送（二期）。
- data agent 写操作与动作执行（批量回复差评、打标等，涉 HITL 审批闸）——首版严格只读。
- text-to-SQL 兜底通道与 Python 沙箱深度分析（二期演化缝，须标注「非核验口径」/容器隔离评估）。
- 商城 agent 深度重组；部署拆分为两个独立服务（先逻辑后物理）。
- 大模型（LLM 本体）微调（沿用既有 out-of-scope 决议）；完整标注界面与训练管线（仅水龙头已落码）。
- 优惠活动的实现（本 spec 仅规划）；行级权限；独立查询计费；时间对比（环比/同比）。

## Further Notes

- **决策溯源**：全部决议的推导、量化依据与备选否决理由在 wayfinder 票 01-20 的 Answer 中（如 dbt 2026 基准、去重后 270 唯一句的实测、注入面实证）；实现期遇歧义以票为准。
- **已落码资产**：意图数据导出 CLI（scripts/export_intent_data.py，--source intent|low_confidence|badcase + 时间窗 → JSONL；15 测试；实测 intent 1966 行/badcase 547 行）——训练数据积累从 2026-09-17 起自动进行。
- **可交互原型**：`docs/wayfinder/mall-data-agent-split/prototype/index.html`（悬浮 agent 上下文联动、订单/商品对比表+雷达图、报告、RBAC 切换账号演示；预置数据已标注）。
- **实现排期建议**（分阶段）：①商城侧三件收口 + 拆读写引擎（前置）；②analytics 子包骨架（MetricQueryEngine + 沙箱 + 销售族迁移 + golden SQL）；③评价/退货/会话族注册 + query_exemplars；④merchant-admin 应用拆分 + 悬浮 agent + PageContext；⑤报告 + RBAC 三层 + 评测面全量；⑥优惠活动（独立 effort）。
- **ADR-0004**（docs/adr/）蒸馏了本 spec 的两个架构级决议：LLM 永不写 SQL 的语义层路线、双 agent 模块缝。
