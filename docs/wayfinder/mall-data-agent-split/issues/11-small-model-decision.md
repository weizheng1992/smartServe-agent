# 11: 小模型决策文档（落点/训练/上线）

Type: grilling
Status: resolved
Blocked by: 05, 06

## Question

**用户常设决议（2026-09-17）：小模型暂不训练，spec 预留插入缝，训练完成后即插即用。** 本票因此从「要不要训」改口径为「缝怎么设计、何时触发训练、接入时怎么验证」：

- **三个插入缝的接口契约**（spec 第③部分核心，引用 05 号的插入点研究）：
  ① 意图分类头缝：`stages/embedding_anchor.py:judge()` 锚点打分块抽出 `IntentScorer` interface，`llm/chat.py` 工厂旁加 `get_intent_classifier()`——默认实现=现状锚点打分，训练后换 adapter；
  ② 指标映射分类头缝：`MetricQueryEngine.resolve()`（09-D5）前端的归一层做成可替换 adapter——默认 L0 词表 + L3 LLM，训练后在 L0 未命中处插 closed-set 分类头；
  ③ 判重缓存换模缝：`semantic_cache.py` 的 `HuggingFaceEmbeddings(model_name=...)` 经配置换路径即全局生效（微调 bge 落位处）。
  统一模式：接口冻结为「问句 → 闭集标签 + 置信度」，训练模型只是缝后的新 adapter。
- **触发条件**：数据水龙头（07 号）累计到什么规模、按什么信号（badcase 率？分类头评测达标？）启动训练（引用 06 号可行性结论定阈值）。
- **训练方案模板**（供将来接入时用，非现在执行）：模型形态（bge 微调 / embedding+线性头 / 小 LLM LoRA）、数据从水龙头到训练集的加工步骤。
- **接入时的评测与灰度方案**：以现有 promptfoo intentF1 为基线对比（同一评测集、隔离训练/评测数据）；影子跑 vs 直接替换、回滚开关。

产出：决策文档（进 spec 第③部分模型策略章节）——重点是缝契约与触发条件，训练本身留待用户日后执行。

## Answer

决议日期 2026-09-17，用户全盘采纳推荐（Q1–Q4）。

### D1 三个插入缝契约（冻结，入 spec）

| 缝 | 位置 | 契约 |
|---|---|---|
| ① 意图分类头 | `stages/embedding_anchor.py:judge()` 抽出 `IntentScorer` 接口；`llm/chat.py` 旁加 `get_intent_classifier()` 工厂 | 问句 → 15 意图闭集标签 + 置信度；默认实现 = 现状锚点打分 |
| ② 指标映射分类头 | `MetricQueryEngine.resolve()` 前端归一层做成可替换 adapter | 问句 → 指标键/维度/方向闭集 + 置信度；默认 = L0 词表 + L3 LLM，训练模型插在 L0 未命中处 |
| ③ 判重缓存换模 | `semantic_cache.py` embedding 模型配置位 | 微调 bge 放配置路径即全局生效，零代码 |

统一模式：**接口冻结「问句 → 闭集标签 + 置信度」，模型即 adapter**——接入 = 写新 adapter + 配置切换，不改编排。

### D2 训练启动触发条件（建议值，启动时机由用户自决）

- 指标映射头：**随时可启动**（150–400 句；按 06 号实测速率几天–2 周攒够）。
- 意图头门槛：唯一标注句 ≥500 且每意图 ≥32（合成扩写占比 ≤50%）+ 71 条冲突队列人审清零。
- 漂移重训信号：intent_conflict 唯一句/周连续两周上升。
- 例程：每月跑水龙头导出统计；连续两月唯一句增速 <300/月 → 转主动造数。

### D3 训练方案模板（入 spec 供日后照做，现在不执行）

- 指标头：embedding + 线性头（SetFit 式少样本：8 条/类可跑、32–64 条/类稳）。
- 意图头：bge 微调或同款线性头。
- 数据加工流水线：`export_intent_data.py` 导出 → 按句去重 → LLM 预标（pipeline winner + structured_llm 双意见）→ 人工只裁分歧 → 评测近邻过滤（cos≥0.90 挡评测句泄漏）→ 10–15% held-out 调三段路由阈值。

### D4 接入时的评测与灰度

- **影子跑先行**：新分类头与现有锚点层并行打分、不出结果只记日志对比。
- 同一 promptfoo intentF1 评测集达标且**高于现有基线** → 配置切换生效。
- **回滚 = adapter 配置回退**（一行配置，不改代码）。
- LLM 精判保留为最终仲裁（三段路由）。
