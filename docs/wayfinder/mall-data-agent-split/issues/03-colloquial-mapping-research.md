# 03: 口语→领域概念映射层设计（data agent）

Type: research
Status: resolved

## Question

商户口语（「上个月卖得最差的」「差评最多的 SKU」「退货率异常的品类」）如何映射到系统的指标/维度/实体？盘点并评估现仓可复用资产：

- `tools_registry/metric_registry.py` 的词表/同义词/conflictGroup 消歧（v2 移植，无运行时消费者）——管得住哪层口语？
- `intent_exemplars` 表 + `triage/exemplar_service.py` 向量召回（租户示例机制）——可否复用为「查询示例库」（few-shot）？
- RAG 知识库（`rag/` KnowledgeEngine，混合检索 + RRF）——数据字典/指标口径文档入 RAG 的价值与边界？
- 小模型分类器——与 05 号票的小模型落点调研衔接（口径映射是否是其最佳落点之一）。

产出：各机制的数据需求、冷启动成本、可维护性、失败模式对比；给出映射层的**分层建议**（哪层管同义词归一、哪层管指标口径、哪层管查询示例、哪层兜底 LLM），供 08 号拍板引用。不拍板。

## Answer

### 1. 现有资产盘点：管得住什么口语（词面实证）

**A. `tools_registry/metric_registry.py`（251 行，v2 1:1 移植）**
- 内容：5 指标（gmv/volume/gross_profit/margin_rate/stock_risk），各带 synonyms（每词表 8-9 词：「卖得好/流水/爆款/压货/滞销」等）、conflictGroup（4 个销售指标同组 `sales_performance_ranking`）、sqlTemplate、businessRules、availableDimensions（仅 p.id/name/category/manager_id）、permissionTag。
- `MetricSemanticResolver.resolve`：纯中文子串匹配 + 最长词优先（「毛利率」>「毛利」），`_GENERIC_PHRASES`（「卖得好」等 7 词）×`_DEFINITIVE_WORDS`（13 词）判歧义；**未命中静默兜底 default=gmv**。
- 消费者：仅 `eval/providers/agent_provider.py` 与 `eval/scorers/metric_disambiguation.py`（promptfoo 评测），运行时零引用。
- 管得住：「销售额最高的」「走量最多的爆款」「哪款毛利最大」「积压最严重」——synonyms 精确子串命中。
- 管不住（票中三例全灭）：「上个月卖得最差的」（词表全正向，无「最差/垫底」反向词；direction 只有 DESC；时间词无解析）、「差评最多的 SKU」（注册表无评论/评分指标）、「退货率异常的品类」（无退货率指标；「异常」是检测语义，排序模板表达不了）。
- 结论：它管得住**词面命中且方向为正的指标词**这一层，约覆盖指标口语的「词典核」；反向、时间、缺指标、非排序语义四类全部漏出。

**B. `intent_exemplars` 表 + `triage/exemplar_service.py`（143 行）**
- 表：business_id（物理租户隔离）/intent_name/example_text/embedding(JSONB)/is_active。检索：租户最近 50 条 → 余弦与 2-gram 文本重叠取 max → 阈值 0.05 → top-3；0.2s 超时降级空（挂 triage 主链）。`llm_refine.py:82-98` 已把召回结果注入 LLM 精判 prompt（few-shot 管道现成）。
- 关键 gap：`intent_name` 的输出空间是**意图名**（order_status/refund），不是「指标+维度+方向+实体」结构——复用为查询示例库需扩 schema（加标注列或复用 intent_name 存结构化标签），检索机制本身可直接复用。
- 冷启动数据：目前无自动沉淀管道（add_exemplar 存在但无调用方回流），示例靠种子。

**C. RAG（`rag/contextual_rag.py` KnowledgeEngine + `knowledge_files.py`）**
- BM25（CJK 单字分词）+ 向量 + RRF 重排，hybrid 0.8/0.2、阈值 0.4；知识源 `docs/knowledge/*.md` frontmatter 声明 businessId/category，按 (business_id, source_url) MD5 比对自愈补灌（改文档自动重灌，幂等）。`search_relevant_docs(category=...)` 参数已存在。
- 现有 5 个文档全是商品知识/门店/SOP（product_knowledge/store_info/operation_guide），**无指标口径文档**——即零代码冷启动缺口：放一个 `metric_glossary` 类别文件即被摄取。
- 边界：RAG 输出无结构文本块，不做归一决策；「卖得最差」与「滞销」口径文档的词面鸿沟需靠文档显式写别名弥合，否则向量/单字 BM25 都可能召不回。

**D. 三层仲裁已有一个映射层活样本**：ADR-0003 `PROFIT_RANKING_RE`（利润词×排行词共现→metric_query 直通）证明「词表前置直通」模式有效但正则散落在 `intent_triage_engine.py`——独立映射层可收编此类补丁。另 `mall_domain.py` 已有实体/品类口语处理先例（`_expand_stem_aliases` 口语统称→货架词素、品类同义词 LLM 判定），实体层不必重建。

### 2. 四机制对比

| 机制 | 数据需求 | 冷启动 | 可维护性 | 主要失败模式 |
|---|---|---|---|---|
| 词表消歧（metric_registry） | 每指标 5-10 同义词，手工 | 零（现成，含评测） | 新指标=加 dict；词表膨胀后子串误伤 | 未命中**静默兜底 gmv**（错答案比空危险）；只正向；无时间/实体 |
| 查询示例库 few-shot | 每指标×维度组合 3-5 条真实问句+结构化标注 | 低（表/检索/注入管道现成；需扩 schema+种子） | 行级增删；50 条上限内存打分够用 | 0.05 阈值松→噪音例句带偏 LLM；租户隔离割裂共性词面 |
| 口径文档入 RAG | 指标口径 md（定义/公式/别名/边界），业务侧一次撰写 | 零代码（放文件即摄取，自愈重灌） | git 版本化，最佳 | 只供 LLM 读不产生确定映射；口语-文档词面鸿沟；召回不稳定 |
| 小模型分类 | 每指标几十条标注+训练/评估管道 | 高（从零标注） | 新指标需重训或退化回 ICL | 置信度失准、分布外、错分无解释 | 

### 3. 分层建议（顺序即执行先后）

- **L0 同义词归一层（确定性，改 metric_registry 为运行时消费者）**：职责=口语词面→canonical metric key + direction + 维度词。必须补：反向词族（最差/垫底/亏→direction=ASC）、泛指词族挂 conflictGroup、时间词（上个月/最近一周）交给 slot/时间解析而非本层；**废除静默兜底 gmv**，未命中即放行下层（诚实空，与 RAG real-data-only 口径一致）。收编 PROFIT_RANKING_RE 类散正则。实体/品类词面不建（mall_domain 已管）。
- **L1 指标口径层（元数据/文档）**：职责=口径真源。metric_registry 本身是机读口径源（description/businessRules/sqlTemplate），口径文档应**从 registry 生成**入 RAG（category=metric_glossary），防双源漂移；供 L3 与 planner 读。新指标（差评/退货率）在此层登记即全链路可见。
- **L2 查询示例层（few-shot）**：职责=词面泛化。扩 intent_exemplars 标注（metric/dimensions/direction/entities），双池：全局共享示例（共性口语）+ 租户示例（叫法差异），检索复用 exemplar_service，注入复用 llm_refine 既有管道；仅在 L0 未命中或低置信时触发，阈值从 0.05 收紧。
- **L3 LLM 兜底层**：职责=长尾与歧义。输入问句 + L1 口径文档 + L2 示例，输出结构化（metric key/维度/方向/实体/置信度）；低置信走**反问**，conflictGroup 天然是反问选项集（「卖得最差指销售额最低还是销量最低？」）。
- 层间契约：L0 命中即终（带 conflictGroup 候选）；L0 未命中→L2 召回高分示例可先例直答；否则 L3；L3 低置信反问。四层共用 metric key 词表作 closed-set，评测挂现有 promptfoo metric_disambiguation scorer。

### 4. 与 05 号票（小模型落点）衔接点

口径映射是小模型候选落点，但**不是从零训分类器**：最佳切入点是 L0→L3 之间的 closed-set 归一分类（输入 L0 未命中问句，输出 5-20 个 metric key 之一+方向），其冷启动数据可由 L0 词表自动造弱标注、L2 示例库积累正例、promptfoo 评测回流 badcase——即「示例库成熟后升级为小模型」的路径；模型形态（微调 vs ICL 注入）归 05 定夺。

### 5. 留给 08 拍板的关键项

① L0 词表归属（留在 metric_registry vs 迁 intent_registry 统一管）；② intent_exemplars 扩列 vs 新表（迁移成本 vs 污染意图分类语义）；③ 口径文档生成方向（registry→doc 单向生成 vs 允许手写双向）；④ 新指标（差评/退货率/复购）登记的先后序（决定词表冷启动范围）。
