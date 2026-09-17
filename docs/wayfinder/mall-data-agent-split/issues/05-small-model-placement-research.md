# 05: 小模型最佳落点调研（意图/映射/缓存）

Type: research
Status: resolved

## Question

「小模型」（自训/微调的轻量模型）在本系统哪里用收益最大？逐个候选落点评估：

- **a 意图分类**：现有三层仲裁管线（规则白名单 → embedding 锚点 `BAAI/bge-small-zh-v1.5` 29 锚句 → LLM 结构化精判 gemini-3.5-flash，`triage/stages/`）中，小模型能替换/加强哪一层？替换锚点层（微调 bge/分类头）vs 替换 LLM 精判层（小分类模型）vs 不值得动；
- **b 口语→指标/维度映射**（data agent）：与 03 号票衔接，分类器把口语归到指标口径；
- **c 查询语义缓存相似度**：相似问句复用既往查询/SQL 的判重；
- **d 其他**：路由分诊、badcase 自动分池等。

每个落点给出：现有实现基线、小模型预期收益（延迟/成本/准确率，能量化则量化）、所需标注数据规模与形态、训练形态（bge 微调 / embedding+线性头 / 小 LLM LoRA）、serving 路径（进程内 sentence-transformers 先例，`llm/chat.py` 工厂）、风险（过拟合租户方言、概念漂移）。产出：落点优先级推荐 + 每落点的插入点（文件/缝，用 codebase-design 语言），供 11 号决策票引用。不拍板。

## Answer

### 0. 管线事实核对（代码精读结论）

- Stage 序列在 `intent_triage_engine.py` 的 STAGES 声明：rule_whitelist → consult_fast_track/duplicate_intercept/slot_fusion → **embedding_anchor** → **llm_refine**。锚点层只覆盖 **3 个粗类**（order_status/refund/out_of_scope，29 锚句，硬阈值 0.85/0.88/0.86，`semantic_cache.py:DEFAULT_ANCHOR_PHRASES`），其余 12 个意图（intent_registry 共 15 档）**全部漏到 LLM 精判**。精判层（`structured_classifier.py:classify`）单次调用做分类+槽抽取+missingSlots+condition+executionMode，gemini-3.5-flash（config.py:46），带租户 exemplar top-3 召回（`exemplar_service.py`，50 行扫描 + 余弦/n-gram 融合，超时 0.2s 降级空）。
- 判重缓存：`SemanticVectorCache.find_best_semantic_match` 原始 bge 余弦 ≥0.96，**进程内**内存 dict（每租户 100 条 / embedding 500 条），读闸在 `stages/embedding_anchor.py:44` 与 `consult_fast_path.py:240`，回填在 `graph/nodes/finish.py:196`。
- 指标映射：`tools_registry/metric_registry.py` 5 指标 + 同义词子串匹配（`MetricSemanticResolver.resolve`）；**运行时唯一消费者是 planner 的 `_ranking_metric_from_text` 词族启发式**（planner.py:36 注释自认 bug：「利润榜变销量榜」）；Resolver 本体只接了 eval provider（`eval/providers/agent_provider.py:53`）。
- 数据资产：`intent_logs`（input_text + predicted_intents + candidates 仲裁留痕 + winner）、`low_confidence_logs`（reviewed 标记）、badcase 池 6 信号源但**仓库零原始数据**（note 只存层/意图名）；eval 55 条（实测 28 条带 expectedIntents，intentF1 阈值 0.8）。**这是回归门，不是训练集**。

### 1. 逐落点评估

#### a1 意图分类 — 替换/加强锚点层（推荐 ★ 最高杠杆）

- **基线**：29 锚句零训练余弦 × 3 类硬阈值；覆盖面 3/15，错杀有实弹（「买个东西怎么买」oos 相似 1.000，已降为提议者）；每条未命中流量 = 1 次 LLM 结构化调用（p50 延迟与成本主驱动）。
- **方案**：frozen bge + 线性头/SetFit，扩到全 15 意图做「高置信直达 / 中置信带 top-k 进 LLM exemplar / 低置信照旧」三段。**不删 LLM 层**——精判还兼槽抽取与多意图编排，纯分类头接不住。
- **收益**：确定性流量占比是关键变量；业界成熟部署 head+回退架构可分流 40-70% 调用。被分流部分延迟从「LLM 调用（百 ms~秒级）」降到 embedding+头（进程内 ~5-15ms，且 user_vector 本来就算），成本同比例降。准确率上 SetFit 类方案在少样本文本分类上普遍打平或超过微调 BERT 与 GPT-3 少样本。
- **数据门槛**：SetFit 8 条/类即可跑通、32-64 条/类稳（HF 官方口径）；embedding+线性头典型 50-200 条/类 → 15 意图 ≈ **0.5k-3k 标注句**。种子可从 intent_logs 挖（predicted_intents 与 winner 一致的高置信样本半自动标），badcase 池/low_confidence_logs 做困难样本。
- **训练形态**：SetFit/冻结 embedding+头 = CPU/单卡分钟级、零新基建；产物 24M 参数（bge-small-zh 本体）或仅头文件。bge 整体微调（MNRL 对比）单卡分钟-小时级，同尺寸产物。小 LLM LoRA = GPU-hours + 需独立 serving（vLLM/量化推理服务），延迟 100ms-1s，运维面 +1，**此处明确不划算**。
- **风险**：租户方言——全局头会抹平租户差异，缓解=头做底座 + 保留租户 exemplar 召回层（现结构天然支持）；概念漂移——意图表 9 月连加 consult/address_manage 两档，需重训节奏 + eval 门（55 条 intentF1）+ candidates 留痕监测，LLM 回退是安全网。

#### a2 意图分类 — 替换 LLM 精判层（不推荐）

- 精判输出是 `StructuredTriageOutput`（意图+槽+缺槽+条件+编排模式），小分类模型无法产出该 interface；小 LLM LoRA 理论可行但标注需含槽位结构（≥数 k 条结构化样本）+ serving 基建 + 漂移重训成本，当前流量下 gemini-flash 按 token 计费远未成瓶颈。**维持 LLM 为最终仲裁者。**

#### b 口语→指标映射（推荐 ★ 数据门槛最低、痛点已立案）

- **基线**：同义词子串匹配 + planner 词族启发式，已知 bug（利润榜→volume）；「最挣钱/哪款划算」类口语零命中走 default 兜底+歧义卡。
- **方案**：5 指标 + conflictGroup 歧义档 = 6-8 类闭集分类，bge+头或 SetFit。**20-50 条/指标 ≈ 150-400 标注句**即超子串匹配；sampleQueries 现成 15 条/指标可作种子（再加 LLM 扩写 + 人审）。
- **收益**：延迟 ~10ms 进程内 vs 现状零模型（无延迟差，纯准确率收益）；准确率收益直接消灭「利润榜变销量榜」类错答（答案口径错误比延迟更伤）。SQL 层契约不动——注册表的 expression/sqlTemplate/conflictGroup/verifiedConfidence 仍是声明式 contract，分类器只产 key。
- **风险**：口径漂移=注册表加指标时需同步加类；缓解=分类器置信度低时回退 conflictGroup 消歧卡（现有交互缝）。

#### c 查询语义缓存判重（中期；先校准后微调）

- **基线**：原始 bge 余弦 0.96 硬阈值，无领域适配。误纳（相似不同义复用错答案）比漏纳危害大——读闸注释里「缓存投毒」加固说明这条缝的敏感史。
- **短期（零训练）**：用标注的 paraphrase/非 paraphrase 对做**每租户阈值校准**，0.96 是 magic number 缝。
- **中期**：bge 微调（CoSENT/MNRL，**1k-10k paraphrase 对**典型量级，可 LLM 生成改写+人审抽查），sharpen 近重复边界。serving 零改动——`get_embedding_model()` 换 `AI_EMBEDDING_MODEL` 指向微调产物路径即全局生效（chat.py:169 工厂 + `_SerializedEmbeddings` 先例）。
- **前置依赖**：数据 agent 的 SQL 复用缓存是 03 号票产物；且当前实现是**进程内存**、多副本不共享（100 条/租户上限）——命中率瓶颈在基建不在模型。**建议排在 03 落地后**。

#### d 其他

- **badcase 自动分池**：`record_badcase_signal(suggested_class=...)` 参数就是现成 seam，意图头（a1）复用即可给池打 suggested_class/聚类，**无需独立模型**；且池零原始数据，先决条件是数据保留策略，不是模型。
- **路由分诊**：triage 本身即路由，已被 a1 覆盖。
- **exemplar 召用**：微调后的 bge 同时提升 exemplar 召回质量——与 a1/c 共享同一产物，边际成本为零。

### 2. 优先级推荐（供 11 号票拍板）

| 序 | 落点 | 数据需求 | 训练成本 | serving 改动 | 预期收益 |
|---|---|---|---|---|---|
| 1 | b 指标映射分类头 | 150-400 句 | CPU 分钟级 | 进程内 | 消灭已立案的口径错答 |
| 2 | a1 锚点层→全意图头+三段路由 | 0.5k-3k 句 | CPU/单卡分钟级 | 进程内 | 分流 40-70% LLM 调用，延迟/成本主杠杆 |
| 3 | c 阈值校准（先行）→bge 微调（03 后） | 校准百级 / 微调 1k-10k 对 | 低/单卡小时级 | 零/换模型路径 | 判重准确率，防错答案复用 |
| 4 | a2 替换 LLM 精判 | ≥数 k 结构化 | GPU+serving 基建 | 新增推理服务 | 不推荐 |
| 5 | d badcase 分池 | 依赖数据保留 | — | — | 复用 a1 产物 |

共性先决：标注工作流（intent_logs 挖掘 + low_confidence_logs 人审闭环）与 eval 扩容是 1/2 的共同阻塞项，属数据票非模型票。

### 3. 插入点（module / interface / seam）

- **a1**：seam 在 `stages/embedding_anchor.py:judge()` 的锚点打分块（62-67 行 `get_anchor_vectors` 消费段）——抽出 `IntentScorer` interface（输入 input_text+user_vector，输出 15 意图分数），判定 1/2/3 的阈值逻辑保持消费 StageVerdict 契约不动。模型工厂缝：`llm/chat.py:get_embedding_model`（lru_cache + local HuggingFaceEmbeddings 先例）旁加 `get_intent_classifier()`；config 旋钮沿 `AI_EMBEDDING_MODEL` 先例（如 `AI_INTENT_CLASSIFIER_PATH`）。
- **b**：interface 已存在——`MetricSemanticResolver.resolve()`。把实现从子串匹配换为 embedding 头（同步 fallback 保底），消费方 planner `_ranking_subtask`/`_ranking_metric_from_text` 收敛到这一单点（顺带修 planner.py:36 自认 bug），eval provider 无感。
- **c**：seam 是 `semantic_cache.py:find_best_semantic_match` 的 0.96 阈值参数 + `_SerializedEmbeddings(HuggingFaceEmbeddings(model_name=...))` 的 model_name——微调产物走后者即全局生效（含 consult_fast_path 读闸与 finish 回填）。
- **d**：seam 是 `badcase/pool.py:record_badcase_signal` 的 `suggested_class` 参数与 `SOURCE_PRIORS` 表，分类头作为新「先验供给者」插入。
- **回归门**：`eval/testCases/*`（55 条）+ `intentF1.scorer.ts`（F1≥0.8）是任何自训模型的准入契约；训练集与评测集必须分离（现 55 条只能当门）。
