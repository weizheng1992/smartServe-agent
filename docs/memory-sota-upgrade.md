# 记忆系统 SOTA 对齐升级（实施基线，2026-10-24）

> 对照物 = 同日调研报告（对话内）与两份外部调研：Mem0 两阶段 op 裁决、Zep/Graphiti
> bi-temporal 失效标记、Generative Agents 三因子检索、LongMemEval 弱项（时序/更新/拒答）、
> ChatGPT/Rufus 的记忆可见可纠正、PIPL 47 条删除权。本文只钉范围与偏差，不复述调研。

## 范围（P0 四件 + P1 合并票）

| 项 | 内容 | 落点 |
|---|---|---|
| P0-1 | episodic 检索补 recency + importance 两因子（**importance 字段此前算了完全没用**） | `memory/episodic_memory.py` |
| P0-2 | 可变维度覆盖扩到「版型」（宽松/修身互斥，同维度新值覆盖旧值） | `memory/long_memory.py` |
| P0-3 | persona 评测集补更新改口/矛盾覆盖/第三人归属三类 case；评分器支持可选 subject 断言 | `eval/testCases/persona/`、`eval/scorers/personaExtraction.scorer.ts` |
| P0-4 | 画像记忆churn（UPDATE/DELETE op）入 badcase 候选池，复用既有 `SOURCE_PERSONA_FACT_DELETED`（auto-draft 源） | `memory/long_memory.py` |
| P1#1 | 审计 op 协议：既有事实清单进 prompt，LLM 裁决 ADD/UPDATE/DELETE/NOOP（targetId 指向既有行）；规则路径（维度覆盖/回声三分）保留为 ADD 兜底与 LLM 失败降级 | `memory/long_memory.py` |
| P1#2 | 结构化画像槽位表 `profile_slots`（user+subject+slot 闭集 height/weight/foot_length/size/fit，UNIQUE 最新覆盖 upsert）+ `read_profile_slots` 读取 + `getProfileSlots` 工具（荐品/尺码终于能消费结构化档案） | `db/models.py`、迁移 0027、`tools_registry/ecommerce_tools.py` |

## 偏差决策（对调研建议的修正，均有理由）

1. **long_memory facts 不加时间衰减**：画像事实（身高175）不随时间失效——失效已由
   superseded 状态机处理；Generative Agents 的 recency 因子针对事件流，episodic 采纳、
   画像不采纳。防"合法旧事实被衰减误杀"。
2. **偏好覆盖只做「版型」**：宽松/修身互斥是真覆盖；颜色/面料/品牌是集合型偏好
   （可以同时喜欢多种，品牌偏好还跨租户并存合法），覆盖会制造假冲突——维持回声去重。
3. **过敏原不进槽位**：多过敏原并存合法，单值 slot 语义错误；留自由文本，后续需要时做
   多值槽。
4. **recordUserPreference 工具写路不进 op 协议**：显式登记语义主体即本人、即 ADD；
   保持现状。
5. **op 不可解析/缺失时一律按 ADD 走规则兜底**：LLM 裁决是增强不是依赖（韧性纪律）。

## 测试接缝（TDD 预定）

1. `fact_dimension_value` 版型提取单测。
2. 密封 PG：版型覆盖/槽位 upsert 最新值/读侧 subject 输出（扩 `test_long_memory_subject`）。
3. op 协议四操作：UPDATE 覆盖 target、DELETE 转 deleted+坏例入池、NOOP 零写入、
   op 缺失按 ADD 兜底（新册 `test_memory_ops_slots`，借 routing 测试桩模式）。
4. episodic 两因子：recency 新旧与 importance 高低改变召回排序（新册）。
5. persona eval 三类新 case（数据驱动，跑真 LLM 的夜间评测管道）。
