# ADR-0015: 本体知识层为 v5 载体——声明式对象-动作语义层;物理拆分家族与 W3C/图数据库/记忆产品栈不采纳

- 日期: 2026-10-19
- 状态: **已决议(批〇·批一·批二·批三全部落地)**
- 上位关系: 关联 ADR-0004(双 agent 模块缝)、ADR-0010(语义层单一事实源——批二吸收 `semantic_model.yaml` 载体时部分修订)、ADR-0012(显式小词表哲学)、ADR-0014(结算核金额纪律,第一红线);无被取代。

## 1. 背景(取证驱动)

### 1.1 领域知识五处散装

| 领域知识 | 现状住所 | 已实弹的病 |
|---|---|---|
| 实体+关系 | `tools_registry/semantic_model.yaml`(12 实体)+ `analytics/schema_cards.py` 手抄列卡 | 手抄卡漂移:`membership` ≠ 真列 `member_level`,错卡正喂进 Data Agent T2 接地 LLM prompt(`t2_explore.py:65-72`) |
| 动作面 | `approval_actions.py` frozenset + gatekeeper 隐式 if/elif + ui TS union + types 冻结契约 | 四形态并存;TS union 多幽灵 `reply` 漏实发 `start_human_takeover`/`release_takeover`;商户台无白名单 + `gatekeeper.py:747` else 兜底 → 拼错动作字符串 = 真实退款工单被静默驳回 |
| 资金阈值 | 免签退款限额缺省散落 ≥6 处 | 50(tenant_config/order_skills/base_skill)vs 100(step_execution_engine 两处 or-100、gatekeeper 形参)vs 租户装配 nike=150/adidas=120——同一笔 80 元退款因代码路径不同结局不同 |
| 不变量 | 散在测试与注释(FK 域闭包/受理集/阈值单源) | 无声明载体 |
| 表所有权 | `merchant_access.py:19` 一行 docstring | 零机械闸 |
| DDL 真相 | `_MERCHANT_DDL` + schema manifest + seed_helpers 三份副本 | 加列须三处同步(f45ea23 曾 43 下游测试连挂) |

**根因诊断:四起实弹全是校验问题,不是表示问题。**

### 1.2 裁决过程

17 个并行 agent 全仓取证(7 路子系统只读调研 + 3 案对案 + 五轴裁判评分 + 5 透镜对抗烤问 + 完整性补漏,2026-10-18/19);选型时效另经 4 路网络实查(2026-10-19,GitHub/PyPI/官方博客一手来源)。

### 1.3 产业定位(2026-10 实查)

本方案形态的产业学名 = **semantic layer × schema grounding × Palantir 式对象-动作操作本体**(a16z 2026-01《The Palantirization of everything》钉为 agent 生产化护城河);背书:dbt 2026-04 基准(语义层内查询 98.2-100% vs 裸 text2SQL 84-90%,语义层答不了会报错、从不静默返回错数)、Cube 2026-06 六控制点(与本仓「服务端模板注入租户谓词 + LLM 永不写 SQL」逐点同构)、ODCS 数据契约 v3.2(2025-12 收口)、dbt 开源 MetricFlow(2025-10)。「ontology for AI agents」的产业主流所指**不是** W3C RDF/OWL。

## 2. 决策

1. **载体 = 分层 YAML 契约包 + pydantic v2 加载校验 + 双语 codegen(批二)+ schema 卡接地(批二)+ MCP 工具面(可选升级路)**。裁决链如实留痕:三案对案五轴评分裁判推荐案 A(代码内注册表,44 分)——用户两轮裁决升维(「不要轻的」「按本体规范目录」),再一轮去格式化(「不用 W3C,用最新的」)→ 终形态 = 案 C 的分层契约包布局,载体取现代栈(YAML 声明 + pydantic v2,非 OWL/SHACL/Turtle)。
2. **三条分层裁定**:①平台级一份本体(全租户共享;租户差异 = 配置数据留 tenant_configs,对应既有 global/tenant 双层画像;商城/后台 = 应用层动作的 faces 曝光面,不是两份本体);②业务数据永远留 PG(知识层零复制实例数据,映射声明驱动对拍);③动态词汇(货架品类词)运行时跟库,不钉死声明。
3. **四批路径与零行为承诺**:批〇试点(环闭合)→ 批一动作面收口 + 四实弹修复 → 批二映射接管(DDL 三真相收一 + generated codegen)→ 批三治理面(文档生成 + CI regen 门)。结算核/技能/图管线/134 端点/SSE 线格式零行为变化;ADR-0014 每步 round 红线全程适用;checkout 的事务语义只被声明(`spans` 三域 + single-conn-single-tx)、不被触碰。
4. **免签退款阈值缺省统一 50**(用户裁决,2026-10-19;收紧方向,三处 50 先例对齐):批一实施,点位 = `tenant_config.py:93`、`order_skills.py:27`、`base_skill.py:36`、`step_execution_engine.py:307,327`、`gatekeeper.py:139`,连同 `run_agent.py:117,145` 自愈装配、`graph/state.py:104`、`db/seed.py:194-198` 种子单源化;租户级显式覆写(nike=150/adidas=120)通道语义不变;`BaseSkill.get_effective_approval_threshold` 租户自治不被吞。
5. **冻结推翻留痕**:portfolio spec §⑥(2026-10-14「冻结新开发、面试准备优先」)经用户 2026-10-19「开工」指令显式推翻,本 ADR 即留痕;配套叙事纪律——对外表述为「双 agent + 技能域 + 本体知识层」,严禁以「多域多 agent 平台」兜售(N3 落选在案,名实不符即 C 级禁语同型)。
6. **批〇验收物(本 ADR 同批落地)**:`ontology/`(core.yaml 闭集词汇 + domain/marketing.yaml 三实体两 join 一维度 + registry.py pydantic v2 加载校验与编译投影 + 一致性门 20 例:parity 5 + 校验负例 15,`services/.venv/bin/python -m pytest ontology/tests` 全绿)。

## 3. 否决项

| 否决 | 理由 | 升级条件 |
|---|---|---|
| schema-per-domain 物理分域 | 422 处裸 SQL;同实例物理 schema 拦不住跨域 join(边界只能靠应用层闸);`ensure_merchant_tables` 无 SET SCHEMA 通道,漏改 DDL 限定 = 自愈幽灵空表数据静默蒸发 | manifest 死闸(ANY 过滤)修复 + 带回滚的一次性搬库脚本 + engine 侧漂移守卫,三前置齐备另立 ADR |
| 域接口化普适禁令(禁直连他域表) | 误杀正当跨域护栏(`delete_spu` 查成交引用);结算核构造性要求共享 conn 的函数签名接口 | 无(以所有权断言替代;所有权矩阵随批二声明化) |
| 售前/售后 agent 拆分 | 复合轮靠 planner 免费编排;记忆/线程按 user+thread 键不可分家;job_resume 硬绑 run_agent | 重议须新 ADR |
| 物理拆库/拆服务 | 结算核单连接单事务横跨三域(`merchant_domain.py:1254-1405`),saga 补偿组件零存量(locked_stock 死列);审批恢复仅进程内派发(ADR-0007 退役 Temporal 后无远程通道) | saga 从零建的完整评估 + 两份结算编排收敛 + 恢复派发通道,另立 ADR |
| W3C RDF/OWL/SHACL 全栈 | RDF 1.2 未成 Rec(2026-10 仍 CR/WD)、SHACL 1.2 规则轨道两派未定、零消费方需三元组/推理;开放世界语义与 fail-fast 闭集纪律相反 | 出现需要推理/三元组的真实消费者 |
| Neo4j 等图数据库 | 层错位(知识/契约面 vs 数据面;命中行业过度设计四条全中);微软 GraphRAG 官方实现全落 parquet;四家主流工具默认内存图,LightRAG 生产推荐 PG;PG→图 = Debezium+Kafka 同步税(多份真相漂移放大版) | 真实多跳实例图消费方(反欺诈关联网络类)或非结构化语料 GraphRAG 上马,届时直接上 Neo4j 2026.x + neo4j-graphrag |
| Zep/Graphiti、mem0、Letta | mem0 OSS v3 已移图记忆转托管付费(SaaS 与数据不出域冲突);Letta 转向 coding-agent 运行时;Graphiti 需新增图库 + 每 episode LLM 抽取;自建四象限记忆无实弹痛点 | as-of 时间旅行查询成硬需求 + 记忆事实过期失效成实弹(两条同现再评估) |
| 运营 agent 走既有审批闸 | 工单绑 thread_id、挂起计划存 task_memory、恢复硬编码 run_agent——运营 agent 无 thread 无处挂;写路径零审计/幂等/回滚 | 两段式建议单形态(agent 只产 proposal,人经 CRUD 执行)或先扩审批内核(agent_type + dispatch 注册表),独立立项 |
| OWL 2 CD(草案曾提及) | 并非真实标准(实为 OWL 2 DL 误写),勘误留档 | 无 |

## 4. 非目标

导购/售后拆分时点;物理拆库;运营 agent 立项(含其建议单形态);MCP 工具面落地(升级路,批三后评估);`semantic_model.yaml` 之外的既有消费方改线(批二前 semantic_model 仍是运行时事实源,ontology 仅 parity 对拍)。

## 5. 后果

- 批〇(本批):环闭合实证,**engine/gateway 零改动零行为影响**;批一(四域+应用层+三面闸+四实弹,预计有意红 3-6 改 4 增);批二(映射接管+codegen,红 2-4);批三(文档+CI 门,近零)。
- `.claude/rules` 的改写随批一/批二消费方接入同批(批〇 无行为变化,不动规则面)。
- **实现偏差留痕(批〇)**:①未入 uv workspace、tests 以 conftest 上仓库根路径引入(零调用方不预建装配;批一首个消费方接入时收编);②marketing 试点仅含域内 join,跨域 join `redemption_of_order`(table=merchant_orders 属 trading)随 trading.yaml 批一落位——域内引用闭合原则,不预建跨域机制;③实体声明含 `table` 键(semantic_model 无此键,parity 投影五键不含 table),为批二表列映射预置。
- **批一落地(2026-10-19 同日)**:四域全量声明(12 实体/9 join/8 维度;registry 两阶段构建,跨域 join 在 base 侧域文件声明、全局实体表校验)+ `application/actions.yaml`(9 动作 + faces/permission/roles + 幽灵 `reply` 登记 + 阈值缺省 50)+ codegen(`engine_py/ontology_generated.py` 自包含分发,漂移门钉死)+ 引擎七处阈值单源(gatekeeper 形参 / step_execution_engine 两处 / run_agent 两处 / graph/state / tenant_config / seed ecommerce,后者含 systemPrompt 文案 $100→$50 的**有意行为收紧**;nike=150/adidas=120 显式覆写保留)+ gatekeeper 受理集显式化 + 入口早退 400 + reject 显式分支 + schema 卡 membership→member_level 勘正 + 商户台动作白名单 400 + gateway 四词表改派生再出口(`__all__` 再出口契约)。回归:engine **1834 全绿**(零意外红——旧 100 缺省与静默驳回路径无存量测试钉住)、gateway **458+3skip 全绿**(基线 454 + 新册 4 例)、ontology 一致性门 **40 例全绿**、ruff 双服务清。
- **实现偏差留痕(批一)**:①permission 真实性断言为 rbac 源码扫描级(`inspect.getsource`),DB 级闭包断言随批三 CI 门升级;②动作语义注记(P4/P5 口径)从 approval_actions.py 行内注释迁至声明 notes,原文保留;③TS 双向对齐断言以文本解析 packages/types 与 ui 的 union 行(pytest 读 TS 为新机制),契约面重构时须同批更新解析器;④ontology 仍未入 uv workspace——engine 消费经生成物而非直接依赖声明层,workspace 收编推迟至批二映射接管时一并裁决(生成物路径已把声明层与运行时解耦,收编紧迫性下降)。
- **批二落地(2026-10-19 同日)**:①schema 卡投影化——`analysis/schema_cards.py` 手抄列卡退役,`MAIN_CARD_TABLES/SPECIAL_FAMILY_TABLES` 由 `registry.card_projection()` 派生(列裁剪 `analysis_columns` 声明层闭包校验;客户表 PII 列 name/phone 刻意不进 T2 接地 prompt);②`semantic_compiler._assert_model_matches_card` 升列级(卡列 ⊆ semantic_model 列,发明列编译期响亮暴露);③gateway manifest 册增本体对拍断言(本体 merchant_db 实体列 ⊆ manifest 真实列集,纯数据零 DB);④`emit_typescript()` → `ontology/generated/ts/ontology-actions.ts`(动作/面/幽灵/缺省,typed const)+ 同步门;⑤codegen 扩实体/卡数据(`ONTOLOGY_ENTITIES`/`CARD_*_ORDER`/两张卡表入生成物)。
- **实现偏差留痕(批二)**:①`_MERCHANT_DDL` 单源化(DDL 由声明生成)**评估后推迟**——其消费面是 gateway 全量契约套件(testcontainers 跑真 DDL),回归成本 > 收益;列级断言 + manifest 对拍已捕获同类漂移,DDL codegen 待物理拆分/schema 变更动议时再议;②`packages/contracts` 前端包推迟——零前端消费方(冻结面照旧手写 + 双向对齐钉住),生成物与同步门已就位,接线随首个真实消费方;③user_coupons 卡注记删去「商城券包;」前缀(与实体注记统一,语义不变,T2 prompt 文本微差);④ontology workspace 收编维持推迟(生成物路径已解耦,见批一留痕④)。
- **批三落地(2026-10-19 同日)**:①知识地图文档生成 `emit_docs()` → `ontology/docs/ontology.md`(词汇闭集/四域实体表/Mermaid ER/动作面表/资金闸缺省)+ 同步门;②CI 三步入册(`.github/workflows/ci.yml` python job):ontology ruff(同口径配置 `ontology/pyproject.toml`)+ 再生成漂移门(`--write-all` 后 `git diff --exit-code`)+ 一致性门(pytest 43 例);③`.claude/rules/tools-registry.md` §1.5 本体知识层节落律(再生成纪律/消费面/新表新列新动作流程/否决与升级条件索引)。词汇全量裁定:闭集词汇以 core.yaml + enum 维度(order_status 等)为载体,**不另立独立词汇表文件**——避免第二真相源(ADR-0012 同哲学)。
- 升级条件汇总见否决项表;任何升级动议须先回读本 ADR 对应行,防止重诉。
