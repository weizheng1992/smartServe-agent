# ADR-0006: Data Agent 架构对照 — LangGraph+MetaRAG+GRPO 全家桶提案 vs 语义层轻管线(现状)

日期:2026-09-19。状态:已评估(结论:核心路线一致,四项能力按触发条件排期,两项明确不采)。
提案来源:业界 2026 主流 Data Agent 建设方案(用户提请对照)。上位决策:[ADR-0004](0004-semantic-layer-route-and-dual-agent-seam.md)、[ADR-0005](0005-data-agent-llm-intent-and-growth-loop.md)、08/15 号决策票。

## 提案摘要

标准四层 + Text→SemQL→SQL:

1. **语义层**:指标字典/维度/口径/权限;MetaRAG 召回指标与表元数据,业务名词映射物理表(不直接喂 schema);
2. **规划推理层**:LangGraph 七节点(intent→metadata 检索→SQL 生成→校验→执行→自省→报告),HITL 审批断点/断点恢复;
3. **工具执行层**:SQL 引擎、Python 沙箱(e2b/matplotlib)、sqlglot 校验、缓存、权限过滤器;
4. **反馈对齐层**:评估数据集(200 条)+ QLoRA SFT → GRPO 微调(可验证奖励:SQL 合法/引用授权指标/结果非空)。

辅助:LlamaIndex(MetaRAG 专用)、DSPy、CrewAI(多 Agent 拆分);基座 Qwen2.5-Coder;明确不推荐原生 LangChain 老 Agent。踩坑四条:不喂全量 schema、不裸执行 SQL、三层保障缺一不可、不一上来多 Agent。

## 两个候选方案正面对比(提案原文的两条路线)

提案实际给出两条候选路线:

- **方案一(全文主体)**:LangGraph 四层全家桶 —— 七节点编排(LLM 生成 SQL)+ MetaRAG 召回 + sqlglot 校验 + e2b 沙箱 + QLoRA SFT/GRPO 微调 Qwen-Coder,让模型学会生成可执行 SQL;
- **方案二(「二、新方案」)**:拆分任务,模型只做语义理解 —— Text → **SemQL(语义查询:指标/维度/过滤,不含物理表名)** → 规则/映射引擎 → SQL;训练目标变为「用户问题 + 指标字典片段 → SemQL」。

| 维度 | 方案一:LLM 生成 SQL | 方案二:SemQL + 映射引擎 | 胜者 |
|---|---|---|---|
| 模型职责 | 意图 + SQL 文本全生成 | 仅语义理解(闭集意图) | 方案二(职责面小一个量级) |
| SQL 正确率 | 生成式:51-62.5%(业界基准);依赖 200+ 标注 + GRPO 才可用 | 闭集内 ~100%(模板预验证) | 方案二 |
| 数据诚实 | **静默错数**(生成式结构性风险,错数不自知) | 响亮失败 + 反问,绝不编数 | 方案二 |
| 口径审计 | 每个 SQL 都是模型新写,口径不可审计 | 模板 = 口径单一事实源,一次审计永久生效 | 方案二 |
| 安全(注入面) | 生成 SQL 需沙箱/白名单/只读账号全链兜底 | bindparams + 白名单,注入面≈0 | 方案二 |
| 权限收敛 | 生成后运行时过滤(可能漏) | 意图层天然收敛(闭集按角色裁剪) | 方案二 |
| 覆盖面 | **长尾 ad-hoc 全可答**(核心优势) | 仅已登记指标/维度 | 方案一 |
| 微调/基础设施 | 必需:LangGraph+LlamaIndex+Chroma+e2b+LangSmith+GRPO 训练管线 | 现有 FastAPI+注册表即可,零新增 | 方案二 |
| 多实体/多表复杂分析 | 强(自由 join/归因) | 需逐族登记模板 | 方案一 |

**判定:主通道采方案二**——高频经营数字需要可信、可审计、权限收敛,方案一的灵活度以「静默错数 + 全链兜底」为代价,与本仓数据诚实铁律(08-P1)结构性冲突;这也是提案踩坑清单自身给出的结论(「不要过度依赖大模型本身」「必须语义层约束」)。

**方案一的正确位置**:不是主通道,而是 ADR-0005 预留的「非核验口径」二期演化缝——面向一次性 ad-hoc 深度分析,输出强制标注,独立评审后启用。两方案不是二选一,而是**可信主通道 + 标注探索通道**的分层。

**本仓现状 = 方案二的已实现增强版**:三级 SemQL 生成(L0 词表/L2 范例/L3 LLM)+ 语义层注册表 + sql_guard 四层闸 + 权限收敛 + 未命中落库增长飞轮,并补齐了方案二没写的三块:实体解析三态(多命中 clarify/零命中响亮失败/陈旧停用)、admin 管理角色与防锁死护栏、PageContext 契约。

## 逐层对照

| 提案 | 本仓现状 | 判定 |
|---|---|---|
| 语义层:指标字典/口径/权限,业务名词→物理表 | `metric_registry.py`(17 指标:别名/口径原文/expression/权限标签/样本问法)+ `schema_cards.py` + `StructuredQueryIntent` 闭集意图(= SemQL) | ✅ 已建,更强:DB 注册表单一事实源 + 17 号漂移断言,非 JSON 文件 |
| Text→SemQL→SQL,不直接 Text2SQL | L0 词表/L2 范例/L3 LLM → `StructuredQueryIntent` → `engine.compile` 模板+bindparams | ✅ 同路线,铁律 08-D1 版 |
| sqlglot 校验/禁 DDL/只读/超时 | `sql_guard.py` 四层白名单 + 只读 reader | ✅(超时/行数上限沿 v2 规格,v3 待核对) |
| LangGraph 七节点编排 | 轻管线(graph.py intake→resolve→compile→execute→卡片→SSE) | 🟡 刻意取舍(15 号决议:单轮问答轻管线;仓库客服主链路本就是 LangGraph,多轮/重试需求出现时迁入现成) |
| MetaRAG 召回指标元数据(LlamaIndex/Chroma) | 闭集目录全量进提示词(17 指标)+ query_exemplars 范例向量库(L2,建成已接线) | 🟡 规模触发:指标 >50 再上召回,当前全量更稳 |
| 模型生成 SQL 节点 | **不做**(08-D1:LLM 只解析意图,永不写 SQL) | ✅ 提案自身也主张 SemQL 优先,节点命名与其主张自相矛盾;本仓彻底版 |
| self_check 结果自省 | 只有诚实空/响亮失败 | ❌ 缺口,值得补(先规则版:行数 sanity/时间窗一致性/实体命中率) |
| 结果缓存 | 无 | ❌ 缺口(高频胶囊问法全命中缓存) |
| Python 沙箱(e2b/matplotlib) | 15 号决议二期评估(打破「LLM 不产出执行代码」,须容器隔离/只读快照/非核验口径标注) | 🟡 未排期 |
| 行级数据权限自动注入 | 未做(0013 决议 v1 不做) | 🟡 二期 |
| HITL 复杂 SQL 审批 | 依赖 text-to-SQL,主通道不存在该问题 | ✅ 不适用 |
| 评估集 200 条 | mapping.json 42 条(生成器逐条真实 resolve 校验)+ dataMapping scorer + golden SQL | 🟡 已有门,量待扩 |
| QLoRA SFT + GRPO 微调 SQL 生成 | `metric_head`(bge+线性头,词表弱标注 seed→shadow→on 三态)+ 评测集纯门永不入训 | 🟡 形态更轻:意图分类已覆盖;SQL 生成微调在铁律下不适用 |
| Temporal 长任务持久化 | 轻管线直调(15 号决议) | 🟡 同 LangGraph 项 |

## 结论与理由

**采用(与提案一致,已实现)**:语义层优先、Text→SemQL→SQL、sqlglot、单 Agent 起步、权限过滤、评估门、只读+防注入。提案的「踩坑四条」与本仓已规避的四项一一对应,互为印证。

**暂不采用+触发条件**:

| 项 | 不采用理由 | 重新评估触发器 |
|---|---|---|
| LangGraph 七节点 | 单轮问答不需要多步循环/断点;轻管线 09 号决议 | 出现多轮追问/失败重试/断点恢复需求 |
| MetaRAG 召回 | 17 指标全量进提示词(~1.5k token)更稳;检索引入漏召风险 | 指标数 >50 或提示词超预算 |
| GRPO/QLoRA | 意图分类用 metric_head(bge+线性头)已够且可灰度;SQL 生成微调违反 08-D1 | metric_head 准确率不达 / 闭集外意图激增 |
| e2b Python 沙箱 | 打破「LLM 不产出执行代码」,须独立评审(容器隔离/只读快照/非核验口径) | 深度归因/自由绘图成为真实需求 |
| 结果缓存 | 查询频次低,收益未显 | 高频问法统计出现 |

**明确不采用**:

| 项 | 理由 |
|---|---|
| LLM 生成 SQL(text-to-SQL 主通道) | 08-D1 已否决:语义层作用域内准确率 ~100% vs text-to-SQL 51-62.5%;生成式静默错数与数据诚实铁律结构性冲突。ADR-0005 后续保留「非核验口径」二期演化缝,须独立评审 |

## 本仓多出、提案未覆盖的能力(实践增量)

- 实体解析三态:多命中→clarify(entity 类反问,点选原词回问)、零命中→响亮失败、陈旧实体→停用范例(ADR-0005 后续①);
- 未命中问句落库 `agent_unanswered`(0015)——覆盖增长飞轮的输入口;
- 权限动态分配:role_menus 勾选即生效 + 静默丢弃修复 + 陈旧范例停用 + 老板/管理员二级管理角色与防锁死护栏;
- 前端 PageContext 契约(路由+勾选实体随问上行)与实体族卡片(订单行跳转勾选)。

## 后续(按触发器排期)

1. self_check 规则版自省(行数 sanity/时间窗一致性)——补三层保障的第三层;
2. 高频问法结果缓存;
3. 评测集 42 → 200(每指标族 15-30 句,18 号契约);
4. 指标 >50 引入 MetaRAG 召回;
5. 多轮/断点需求出现时迁 LangGraph StateGraph;
6. text-to-SQL「非核验口径」二期缝独立评审。

## 附:微调技术栈对照(2026 主流 QLoRA/DoRA/DPO/GRPO 提案 vs 本仓 metric_head 现状)

提案结论:QLoRA 单卡首选、DoRA 精度升级、DPO 适合对话偏好、**GRPO 适合带可验证奖励的 Agent 任务**;框架 Unsloth(单卡快速)/LLaMA-Factory(中文生态)/Axolotl(多卡生产)。

### 本仓现状(已在做的「微调」)

metric_head 训练闭环(`scripts/training/` + [训练文档](../training/metric-head-training.md)):词表自动造弱标注 590 句(seed_from_registry)→ prepare_data → train(bge-small-zh 嵌入 + 线性分类头)→ evaluate(heldout 98.9%)→ 部署(AI_METRIC_HEAD 三态 shadow/on,回滚=删环境变量)。这等价于提案表格里「单卡快速实验,小样本分类」的极简形态——模型不是 LLM,是嵌入+线性头,但「弱标注→训练→灰度→回滚」的工程闭环完整。

### 何时需要升级到 LLM 微调(触发器)

| 触发器 | 动作 |
|---|---|
| ① metric_head heldout 准确率跌破阈值 / 闭集外意图激增 | 自托管 Qwen2.5-7B-Instruct,QLoRA SFT 微调「问句→SemQL」(训练样本=mapping.json 同格式) |
| ② bigmodel API 限流(实测 429,详见实弹记录)/成本/延迟不可接受 | 同①——自托管同时解决限流依赖 |
| ③ 意图解析准确率要求超过 prompt+小模型上限 | TRL GRPO:**可验证奖励已现成**——SemQL 过闭集校验+实体命中+口径匹配即 dataMapping scorer 的奖励函数(提案「Agent 工具调用选 GRPO」的典型场景) |

### 约束(不变)

- 08-D1 铁律:微调目标永远是「语义理解 → SemQL」,**任何微调都不能让模型产出 SQL 文本**;
- 18 号不变量:评测集纯门永不入训,seed_from_registry 弱标注需过滤评测集近邻(cos ≥ 0.90 已实现);
- bigmodel API 是外部服务不可微调——LLM 微调的前提是自托管模型(前置成本,按触发器①②评估)。

### 技术栈对照(提案推荐 vs 本仓适用性)

| 提案推荐 | 本仓判定 |
|---|---|
| QLoRA(Unsloth 单卡) | ✅ 升级触发时首选(自托管 Qwen 意图模型) |
| DoRA | 🟡 同 QLoRA,精度优先时替换 |
| DPO | 🟡 客服主链路(finish 话术)可适用,非 data agent |
| GRPO | ✅ 触发器③的候选:SemQL 可验证奖励(闭集+实体+口径)天然构成 reward |
| GaLore/PiSSA/VeRA/TorchTune/Axolotl/ms-swift | ❌ 当前规模不需要;多卡生产再评估 Axolotl |
