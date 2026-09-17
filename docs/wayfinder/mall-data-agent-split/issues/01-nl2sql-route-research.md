# 01: 「口语→SQL」编译路线对比（data agent 技术路线研究）

Type: research
Status: resolved

## Question

商户 data agent 把商户口语编译成安全 SQL，该走哪条主路线？调研并对比三条：

- **A 语义层/指标注册表扩展**：扩展现有 `services/engine-py/src/engine_py/tools_registry/metric_registry.py`（词表/同义词/conflictGroup 消歧/sqlTemplate，v2 移植而来，目前无运行时消费者），查询只命中预置指标模板；
- **B LLM 动态生成**：LLM 按 schema 现场生成 SQL，加校验护栏；
- **C 混合**：指标优先命中，未命中再走动态生成。

对照仓库内既有事实：`tools_registry/order_domain.py` 的 `query_product_ranking`（唯一运行时统计工具，手写 SQL 聚合商户真单，五指标口径）；v2 `NLMetricQueryEngine` 规格（`docs/specs/production-resiliency-and-multi-tenant-safety.md` 中 NL→SQL 编译与多租户安全设计，TS 实现已删）。业界参照（web 调研）：Vanna.ai 的 RAG+SQL 生成、LangChain/LlamaIndex SQL Agent、dbt semantic layer / Cube 的指标层思路、业界 text2sql 护栏实践。

产出：三路线的能力边界（能答什么问题、答不了什么）、维护成本、失败模式（幻觉 SQL / 口径漂移 / 注入面）、与现仓资产复用度、适用规模段的事实对比表。**只给事实与利弊，不拍板**（拍板在 08 号票）。

## Answer

标注约定：【代码事实】= 本仓可验证；【业界】= web 调研经验，附来源。

### 1. 现仓资产能力面【代码事实】

**metric_registry.py**（`services/engine-py/src/engine_py/tools_registry/`，v2 TS 1:1 移植）
- 5 指标（gmv/volume/gross_profit/margin_rate/stock_risk），每条 ~20 字段：expression、sqlTemplate、中文口语 synonyms、conflictGroup、businessRules、availableDimensions、permissionTag（sales_viewer/warehouse_operator/finance_owner，**未接线**）、verifiedConfidence、sampleQueries。
- `MetricSemanticResolver.resolve()`：key/label/同义词**子串匹配** + 最长匹配优先 + 泛指词/定值词启发式判歧义；未命中默认兜底 gmv 且 `hasAmbiguity=True`。
- `render_sql()`：对模板做 `str.replace()`，filters/dimensions/limit 全是字符串插值——**无绑定参数**，正是 v2 规格 §3 点名的注入面。
- grep 证实**零运行时消费者**；sqlTemplate 面向 engine 本地表（products×order_items），与真实事实源 agent_merchant 镜像库已 **schema 漂移**；模板本身不含排除 REFUNDED/CANCELLED 口径（业务规则只写在 businessRules 文字里，不在 SQL 里）。

**order_domain.py `query_product_ranking`**（唯一运行时统计工具）
- 注册为工具 `queryProductRanking(rankingMetric/managerOnly/category/limit)`，LLM 传指标键。手写 SQL 走商户镜像库（merchant_spus×skus×预聚合明细），SQLAlchemy bindparams 参数化；排除退款/取消单、ON_SALE 过滤、gmv/volume 榜 HAVING qty>0、cost_at_purchase NOT NULL 故意报错可见、明细预聚合防笛卡尔放大。
- 能力边界：仅 5 指标排行 + category + top-N；**无时间范围**（TODO Phase 1b：nlQuery 中文时间解析未移植）、无任意维度/过滤组合、无新指标扩展位。
- 未知指标键**静默回退 gmv**（`raw_str if raw_str in registry else "gmv"`）——静默失败型。
- 无 READ ONLY 事务 / statement_timeout / 行数上限——v2 规格的三道沙箱在 py 移植中缺失。
- 自带第二份**简化版 METRIC_REGISTRY**（仅 key/label/unit/direction）。

**v2 规格 NLMetricQueryEngine**（`docs/specs/production-resiliency-and-multi-tenant-safety.md` §3，TS 实现已删）
- `compile()` → `CompiledSQL{text, values}`：租户/经理/过滤值/分页上限一律 `$1/$2` 位置参数。
- `executeReadOnlyAnalyticsQuery`：`SET TRANSACTION READ ONLY` + `statement_timeout=3000ms` + 50 行绝对上限；对抗测试样例 `' OR 1=1; DROP TABLE products; --`。
- 本质是「语义注册表 + 参数化编译 + 只读沙箱」= 路线 A 的安全完成态，而非自由生成。

### 2. 业界参照【业界】

- **dbt Labs 2026 benchmark**（dbt-labs/dbt-llm-sl-bench）：语义层作用域内 SL 准确率 100%（两个 2026 模型）vs 裸 text-to-SQL 51–62.5%；**作用域外（跨实体多跳）SL=0% 但响亮失败（报无法回答），text-to-SQL 70–100% 但静默错数**；text-to-SQL 需全量 schema 进上下文，大库不可行。dbt 官方推荐工作流即路线 C：先查 SL → 小缺口补建模 → 仍不行降级 text-to-SQL。
- **反例**：MotherDuck 实测小而整洁 schema 上 text-to-SQL 可达 ~95%，无需语义层。
- **Vanna.ai**：RAG（DDL+文档+问答-SQL 对入向量库，检索 ~10 条拼 prompt）→ LLM 生成 SQL。依赖持续人工策展；相似表易混；跨向量库结果不一致；社区结论适合内部分析、不适合客户面多租户 SaaS（issue #317 还反映安全上无法把生成 SQL 限定到训练数据子集）。官方新推 **Function RAG**：高频问答-SQL 模式固化为**可调用参数化模板（函数/工具）**，LLM 生成作补充——路线 C 的业界直接先例。
- **Cube / dbt SL**：headless BI，指标+维度+访问控制+缓存经 REST API 服务，作为 NL 接口可信接地层；建模质量决定上限（垃圾进垃圾出同样适用）。
- **护栏实践**：真正边界是**数据库只读角色**（应用层校验不可作唯一防线）；role 级 statement_timeout；执行前 sqlglot 类解析校验（单语句、拒注释、写关键词黑名单、表白名单）；只读角色仍有系统存储过程/多语句拼接缺口。

### 3. 三路线事实对比表

| 维度 | A 语义层/注册表扩展 | B LLM 动态生成+护栏 | C 混合（指标优先+兜底生成） |
|---|---|---|---|
| 能答什么 | 指标×白名单维度×过滤组合；口径可审计 | 任意可映射到暴露 schema 的问题：时间范围、比较、未建模 join、长尾 | A 的确定域 ∪ B 的长尾 |
| 答不了什么 | 未注册指标/维度/时间范围【代码事实：现无时间过滤】；跨实体多跳【业界】 | 无硬性「答不了」——代价是可能**静默答错**【业界】 | 取决于路由判定；B 侧缺陷不消失 |
| 失败模式 | 可响亮失败（未命中可报告/澄清）；但现 render_sql 有注入面【代码事实】，需按 v2 §3 参数化 | 幻觉列/join、口径漂移、run-to-run 不一致、静默错数；prompt 注入→SQL 注入【业界】 | A+B 失败模式叠加 + 路由误判新失败面；须按来源标注答案可信级 |
| 口径一致性 | 模板单一出处，可版本化审计 | 同问不同答【业界：dbt 实测】 | 命中 A 一致，落 B 不保证——需产品层区分呈现 |
| 维护成本 | 每新指标=注册条目+评测；模板 schema 漂移需治理（现已漂移【代码事实】） | schema 上下文/评测集/护栏持续策展（Vanna 经验：重在数据策展不在代码） | A+B 之和 + 路由器与来源标注的新面 |
| 现仓复用度 | 最高：registry+resolver+v2 沙箱规格全在；query_product_ranking 即「单指标手工物化」先例 | 低：registry 仅可作 few-shot 上下文；可复用 v2 §3 沙箱设计与商户只读引擎 | 复用 A 全部 + B 护栏蓝图；新增路由与双路径运维 |
| 注入面 | 参数化后≈0（若补 v2 §3）；现状 render_sql 有洞【代码事实】 | 最大，靠只读角色+timeout+解析校验+行上限纵深压制【业界】 | B 子域同 B，A 子域同 A |
| 适用规模段【业界】 | 准确性关键（对客展示/KPI/审计）、大而乱 schema、企业级 | 内部运营 ad-hoc、探索、原型、小而整洁 schema | 长尾需求真实、要扩覆盖率但不逐指标冲刺注册表 |

### 4. 各路线利弊

**A** 利：口径唯一出处、失败响亮、permissionTag 可收权限（字段已在【代码事实】）、dbt 数据支持域内准确率上限最高；v2 规格即为此路线的安全形态背书。弊：覆盖率=注册表大小，每扩一格都是工程动作；模板已与真数据源漂移，说明**治理本身即持续成本**；子串匹配器精度有限（「最近 7 天卖了多少」直接超纲——无时间槽）。

**B** 利：覆盖率上限最高（dbt 作用域外 70–100% vs SL 0%）；零注册表维护。弊：静默错数是结构性风险（dbt：域内仅 51–62.5%）；对客多租户场景被社区实践明确劝退；护栏栈（只读角色/timeout/解析校验/行上限）一样要建——维护成本从「指标注册」换成「安全工程+评测集」；全 schema 上下文随库增长不可扩展。

**C** 利：与 dbt 官方推荐工作流同构；Vanna Function RAG 先例；高频问题享 A 的确定性、长尾有 B 的覆盖；兜底层可降级 SLA（限频、标注「非核验口径」、仅管理员可见）。弊：系统面最大（两套+路由+来源标注）；路由误判时体验取决于标注诚实度；B 侧护栏一个都不能省。

### 5. 交叉发现（供 08 号票决策输入）

1. 现仓事实上已有「隐性 C」：LLM 选 rankingMetric 键、未知键**静默落 gmv**——无论选哪条路线，该静默回退都应改为响亮失败或显式澄清【代码事实】。
2. 同 5 指标现存 **3 处定义**（metric_registry 全量、order_domain.METRIC_REGISTRY 简化版、v2 规格口径描述），且 metric_registry 模板指向的表与 query_product_ranking 实查的库不同——任何路线都先要收敛单一事实源，否则「语义层保证口径一致」的前提不成立【代码事实】。
3. v2 §3 的参数化+只读沙箱是 A/C 共用地基、B 的硬前提，与路线选择正交【代码事实（规格在，实现缺）】。
4. 时间范围解析（nlQuery 未移植）是用户感知最强的能力缺口，三条路线都绕不开它归属哪层（模板 filters 槽 vs LLM 生成 where）【代码事实+待 08 决策】。

### 参考

- [dbt Labs — Semantic Layer vs. Text-to-SQL: 2026 Benchmark Update](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026)
- [Vanna — Introducing Function RAG for SQL Generation](https://ask.vanna.ai/blog/functionrag.html) / [vanna-ai/vanna](https://github.com/vanna-ai/vanna)（含 [issue #317](https://github.com/vanna-ai/vanna/issues/317)）
- [MotherDuck — Text to SQL at 95% Accuracy. Do You NEED a Semantic Layer?](https://www.youtube.com/watch?v=j2G4PWCq10k)（反例）
- [Cube — Embedded Agentic Analytics](https://cube.dev/blog/announcing-embedded-agentic-analytics)
- [Particula — Text-to-SQL Agent Permissions: The Role Is the Boundary](https://particula.tech/blog/text-to-sql-agent-database-role) / [fastero — SQL Query Guardrails](https://fastero.com/blog/how-to-set-up-sql-query-guardrails-for-your-data-team) / [Safe Text-to-SQL (dev.to)](https://dev.to/kowshik_jallipalli_a7e0a5/safe-text-to-sql-giving-an-agent-database-access-without-dropping-tables-or-leaking-pii-i47)
