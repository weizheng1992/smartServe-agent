# 18: data agent 评测面设计

Type: grilling
Status: resolved

## Question

spec 的 Testing Decisions 章节素材（fog 毕业：08/10 已决）——data agent 的评测怎么建：

- **映射层评测集**：L0–L3 归一评测（问句 → metric key / 维度 / 方向 / 时间窗），挂现有 promptfoo 体系（eval/testCases/ + scorer）；与现有 metric_disambiguation scorer 的关系（扩展为全映射面 or 新 scorer）；
- **golden SQL 集**：每指标族的基准 SQL + 种子数据期望结果，防口径回归（销售族可直接从 query_product_ranking 现行为冻结）；
- **回归门**：哪些进 CI（映射评测必须过？golden SQL 对种子库跑？）；
- **问句域隔离**：data agent 问句是新 testCases 文件族，与现有 55 条意图评测集的关系（互不污染，也为 11 号训练/评测隔离打基础）。

## Answer

决议日期 2026-09-18，用户全盘采纳推荐（Q1–Q4）。

### D1 映射评测 = 新建 dataMapping scorer + 新 testCases 族

- 断言四要素：metric key / 维度 / 方向 / 时间窗；provider 直调 `MetricQueryEngine.resolve()`（复用 metric_disambiguation 直调 resolver 的模式）。
- 新文件族 `eval/testCases/data_analytics/`；种子 = 10 号六胶囊原句 + 每指标族 15–30 句（L0 词表词、反向词、时间窗变体）+ **反问/不支持案例**（期望 ClarificationRequest 或响亮失败，禁止静默兜底——08-P1 的回归门）。

### D2 golden SQL 集 = 双冻结

- 每指标族一条基准 SQL + 种子数据期望结果；销售族从 `query_product_ranking` 现行为冻结（作为迁移前后行为不变的证明）；评价/退货/会话族实现时同步交付。
- 执行环境复用 17 号 D1 的 CI 临时 postgres 种子库。

### D3 回归门 = 两者进 CI、必须绿

- dataMapping 评测 + golden SQL 比对是 data agent 相关 PR 的合并门；现有 55 条意图评测集照旧跑（商城面回归）；L3 LLM 依赖的评测沿用 promptfoo 现行 provider 模式。

### D4 隔离 = 写成 spec 单条不变量

- data agent 问句独立文件族，与客服意图域物理分开；**评测集冻结为纯门、永不入训**（06 号）；训练启动执行 11-D3 近邻过滤（cos≥0.90 挡评测句泄漏）——三票口径同一根线，spec 表述为一条不变量。
