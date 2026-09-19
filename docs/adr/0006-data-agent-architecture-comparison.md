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
