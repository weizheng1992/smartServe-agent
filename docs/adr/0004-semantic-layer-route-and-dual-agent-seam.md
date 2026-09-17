# ADR-0004: data agent 语义层路线（LLM 永不写 SQL）与双 agent 模块缝

- 日期: 2026-09-18
- 状态: 已决议（wayfinder 图 mall-data-agent-split 20 票收官；完整实现决策见 `docs/specs/mall-data-agent-split.md`）
- 关联: ADR-0002（真实销量聚合口径）、v2 NLMetricQueryEngine 规格（production-resiliency-and-multi-tenant-safety.md §3）

## 背景

smartServe-agent v3 需要商户侧数据分析能力（销量/差评/退货/会话指标），同时把员工工具从 C 端商城应用拆出。wayfinder 图（20 张决策票，5 份研究票含 web 调研与真实库实测）对「口语→SQL 走哪条路线」「两个 agent 怎么分缝」做了完整裁决。

## 事实基础（2026-09 票证）

1. 业界基准：语义层作用域内准确率 ~100%，text-to-SQL 51-62.5%（2026 模型已近翻倍仍不足）；且范围外语义层响亮失败、生成式静默错数——与本项目数据诚实铁律结构性冲突。
2. 本仓实证：metric_registry 的 render_sql 裸 str.replace（注入面）、指标定义 3 份漂移副本、未命中静默兜底 GMV、「利润榜答成销量榜」已立案错答。
3. v2 规格已设计过与路线无关的沙箱（位置参数 + READ ONLY + 3s + 50 行），实现缺位。
4. 商户库仅 7 表（小 schema = 语义层友好段）；triage 是 C 端客服意图域（15 意图/槽位/资金闸），与商户分析域不同域。

## 决策

1. **语义层为唯一执行通道，LLM 永不写 SQL**：LLM 的位置在映射层（问句→闭集结构化查询意图：指标键/维度/方向/实体/时间窗），执行面 100% 指标模板（fragment 闭集 + bindparams + 沙箱）；未建模问题响亮失败 + 反问；text-to-SQL 兜底不做（二期演化缝须标注「非核验口径」）。
2. **双 agent 模块缝**：data agent 独立轻管线（不进 9-Stage triage，engine 内两图并行）；入口挂商户员工鉴权面新路由组（不混 C 端 chat）；共享=会话/推送/卡片约定，分离=triage/记忆/审批 vs L0-L3/编译器/沙箱；落点 engine_py/analytics/。商城 agent 仅三件收口（注册表收敛、散正则收编、queryProductRanking 换底层保工具面）。
3. **小模型缝预留**：意图分类头（IntentScorer）/ 指标映射 adapter / 判重缓存换模位三缝冻结「问句→闭集标签+置信度，模型即 adapter」；暂不训练，数据水龙头已落码积累。

## 否决项

- text-to-SQL 主通道（静默错数 + 注入面 + 口径不可审计；对客多租户被社区实践劝退）。
- pglast（GPL 法务负担）、sqlparse（non-validating 不可作安全边界）。
- data agent 复用商城 step 执行体系/审批引擎（只读分析用不上，过度工程）。
- 商户库 v1 上 alembic（7 表单部署，幂等 DDL + 漂移断言够用）。

## 实现要点

MetricQueryEngine 深模块（resolve/compile/execute + 四错误模式 + 两不变量：用户输入永不进 SQL 文本、business_id 永不被调用方触达）；四层 SQL 校验链（sqlglot 解析/编译参数化/DB 只读沙箱/呈现诚实）；前置工程=拆 _merchant_reader_engine 读写共用。评测门 = dataMapping scorer + golden SQL 双冻结进 CI。

## 后果

新指标覆盖 = 注册表工程动作（换来口径可审计）；实现排期六阶段见 spec Further Notes；若真实问句分布证明长尾成规模，二期按演化缝重新谈判降级通道。
