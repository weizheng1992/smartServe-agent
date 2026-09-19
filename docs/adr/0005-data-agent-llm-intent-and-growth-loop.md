# ADR-0005: data agent L3 LLM 意图层实装 + 查询族扩容 + 覆盖增长机制

日期:2026-09-19。状态:已采纳(用户按推荐全盘拍板)。上游:[ADR-0004](0004-semantic-layer-route-and-dual-agent-seam.md)、08/13/15/18 号决策票。

## 背景

data agent 上线后暴露覆盖面问题:问法必须落在 82 条同义词 + 3 种时间窗 + 9 品类的词面内,"某个活动卖得怎么样""活动里某款对比其他款""张三最近的订单"等真实经营问题全部响亮失败。用户诉求:**根据任意用户输入回答,并持续覆盖更多数据问题**。

## 决策

1. **守住 08-D1 铁律**:LLM 只做语义解析(问句 → 闭集结构化意图 + 实体提及),SQL 仍 100% 指标模板 + bindparams + sql_guard;text-to-SQL 兜底本期不做(二期演化缝保留,启用须独立评审并标注「非核验口径」)。
2. **两级路由**:L0 词表先命中(零 LLM、零时延)→ 未命中 L2 范例回放(query_exemplars ≥0.90,建成未接线 → 接线)→ 未命中 L3 LLM 意图(`llm_intent.llm_resolve`,`get_chat_model().with_structured_output`,grounding = 指标闭集目录 + 九品类 + 三时间窗)。`AI_INTENT_L3=off` 一键回滚。
3. **实体槽**:意图新增 `entity_slot`(promotion/customer/spu → 解析后 ID)。LLM 只出「实体提及」原文,落库命中由 `dimensions.py` 确定性完成(ILIKE);唯一命中绑定、多命中 → clarify(entity 类反问,点选原词回问)、零命中 → 响亮失败。活动效果采用**核销关联口径**(真实归因)。
4. **查询族扩容(首批矩阵成员)**:`promo_effect`(活动效果总览)、`promo_sku_compare`(活动内商品对比,目标款标记)、`customer_orders`(客户订单列表卡,前端行级「在订单中查看」跳订单管理并勾选,复用 PageContext 契约)。
5. **覆盖增长机制**:①unsupported 问句落库 `agent_unanswered`(0015)——真实问题驱动语义层登记;②模板矩阵化方向:指标 × 维度(活动/客户/SPU/品类)组合,新覆盖 = 登记新维度而非新项目;③评测门随扩容同步(18 号契约)。
6. **事实缺口顺手修复**:clarify 选项按角色闭集过滤(13 号票欠账);metric_head on 路径补 limit/时间窗/品类槽位(与 L0 同源 `_extract_slots`);前端 ask 改逐帧流式渲染(SSE 本为流式,原实现整段等待)。

## 否决项

- text-to-SQL 主通道(08-D1 已否决,理由不变:静默错数 + 注入面 + 口径不可审计)。
- L3 失败时静默回落到最近似指标(违反 08-P1)。

## 后续(未排期)

- 时间窗扩展(昨天/本周/环比)、品类维度的引擎侧实现、维度矩阵的更多组合模板。
- text-to-SQL 演化缝独立评审(非核验口径标注 + 只读沙箱复用)。
- mapping.json 补满每指标族 15-30 句并进 CI(当前 38 条 + promptfoo.data.yaml 已建)。

## 验证

- engine/gateway 契约与单测全绿(新族编译形状、实体必传响亮拒绝、L2/L3 兜底、unanswered 落库)。
- 前端 vitest 53+ 用例(增量 SSE 解析撕裂容忍、实体反问原词回问、订单卡跳转写选中集合),`tsc && vite build` 绿。
- 实弹:真实问句(活动效果/客户订单)经 L3 解析执行;未命中问句落 agent_unanswered。
