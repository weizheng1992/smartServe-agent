# 意图路由升级方案(P1 语义路由 / P2 蒸馏小分类器)

2026-09-23 立项。前置:P0 置信度级联已落地(`LlmRefineStage` 终局澄清,
`INTENT_CONFIDENCE_ROUTE=0.5` + 按意图覆盖,见 `intent_registry.py`)。

业界对照(2025/2026 共识):规则/语义快层在前、LLM 精判居中、低置信澄清或
转人工收尾——本系统骨架已符合;差距在置信度信号不可用、语义路由未成层、
反馈标签未回填。

## P2 数据盘点结论(2026-09-23,dev 库实测)

| 项 | 数值 | 含义 |
|---|---|---|
| intent_logs | 2045 条(09-02~09-22) | 三周真实流量 |
| winner 分布 | order_return 362 / shopping_guide 317 / cart_manage 265 / order_status 193 / order_query 185 / consult 171 / general_query 108 / refund 52 / **promotion_query 44** / address_manage 40 | 覆盖全 14 档位 |
| LLM 自报置信度 | **98% ≥0.9**(<0.5 为 0) | 自报置信无判别力,业界已知过度自信 |
| candidates 数组 | 1764 条;≥2 条 1130;**跨≥2 层 1027;意图不一致 1125** | 蒸馏硬样本金矿 |
| actual_outcome 回填 | **0/2045** | 监督标签缺失——P2 的真正瓶颈 |
| low_confidence_logs | 4(P0 上线当天起积累) | 澄清分流后将持续增长 |
| badcase_candidates | 584(intent_conflict 520 / circuit_breaker 49 / approval_rejected 12 / claim_mismatch 2) | 已有负样本池 |

**结论:暂不具备直接训练条件,瓶颈不是量是标签。** 2045 条输入里 1125 条
多层不一致样本是现成的难例,但没有 ground-truth 档位(actual_outcome 全空,
人工定性仅在坏例池 520 条 intent_conflict 里以 candidate 态存在)。直接拿
winner 当标签训模型 = 把 LLM 的偏见蒸馏进去。

**P2 启动条件(按序):**
1. actual_outcome 回填机制:澄清反问(P0)的用户后续选择、人工定性的坏例
   审结、nightly 矩阵对历史问句的复判——三者任一即可产生 silver label;
   ✅ 通道①已上线(2026-09-23):澄清后首轮终局 winner 自动写回澄清行
   actual_outcome(log_intent_to_db 内联 backfill_clarify_outcome,30 分钟
   窗口/只认最新待回填行/降级兜底不作标签源,回归 4 钉);
   ✅ 通道②已上线(2026-09-23):scripts/review_badcase.py 人审 CLI ——
   list(待审候选附线程最近终局)/label(定性→回写 actual_outcome,坏例置
   labeled)/dismiss(非缺陷不动标签);520 条 intent_conflict 积压由此
   消化,回归 4 钉);
   ✅ 通道③已上线(2026-09-23):scripts/backfill_outcome_from_rules.py
   —— SlotExtractor 单规则高置信复判历史问句批量回填(歧义/零命中/
   低置信跳过;澄清行排除走通道①)。首跑 dev 500 行:可贴 373(74.6%),
   歧义 38/零命中 89 跳过;回归 6 钉(单规则贴/多规则 None/确定性)。
2. silver label ≥3000 条且每档位 ≥150(当前 12 个活跃档位,需 ~1800 有效);
3. 训练走既有 SFT 轨基建(QLoRA/PAI,换分类头或小模型),评测以 nightly
   矩阵 + 坏例池复判为门。

## P1 设计:embedding_anchor 升级为语义路由层

**目标**:高频/词面可判的意图在 LLM 之前毫秒级出高置信提议,减少对结构化
精判的依赖;LLM 只接语义路由不达阈值的尾部。

**数据结构**(新增 `intent_routes.json`,随意图注册表同源维护):
```json
{
  "promotion_query": {
    "utterances": ["有什么优惠活动", "推荐优惠最大的商品", "叠加减的最多的商品",
                   "哪款优惠力度最大", "优惠券怎么领", "满减怎么算", "有折扣吗"],
    "threshold": 0.82,
    "skill": "skill_promotion_query"
  },
  "shopping_guide": { "...": "同构,6~10 条/意图" }
}
```
- 每意图 6~10 条锚点例句(从 nightly 矩阵问句 + 词表派生,人工过一遍);
- `threshold` 用 dev-set 标定:nightly 矩阵全部问句过 embedding,按意图取
  最优 F1 阈值(aurelio semantic-router 的 dev-scores 模式),写入配置;
- 首次构建把全部锚点向量入内存(BGE 已有缓存,14 意图 × 10 句 ≈ 140 向量)。

**判定逻辑**(替换 embedding_anchor 现有单锚点逻辑,接入点不变):
1. 输入向量与全部锚点算余弦,取每意图最高分;
2. 最高分 ≥ 该意图 threshold → 产出 `_proposal("semantic_router", intent, sim)`
   高置信候选,交 skill_fast_track 直达技能;
3. 低于全部阈值 → 维持现状落 LlmRefineStage(P0 澄清兜底不变);
4. 语义路由提议与规则层冲突时,现有资金否决/仲裁留痕原样生效。

**与并行会话的冲突面**:仅 `triage/stages/embedding_anchor.py` 与新增配置
文件,不碰 graph.py/session_store;待其意图层改动合入后再动工。

**验收**:nightly 矩阵全绿不回退;语义路由命中率(免 LLM 占比)与误路由数
(坏例池 intent_conflict 增速)双指标入巡检日报;线上 A/B 先影子跑(只记提议
不接管路由)一周,误路由率 < 现状再切主路径。

## 里程碑

- M1(并行会话意图层合入后):锚点集 + 阈值标定脚本 + 影子跑;
- M2:P0 数据跑满 2 周 → 复核阈值与澄清命中率,调 `INTENT_ROUTE_THRESHOLD_OVERRIDES`;
- M3(P2 启动门槛):silver label 达标 → 训练 → nightly+坏例池双门验收 →
  影子对比 → 替换 LlmRefine 为主精判,LLM 降为抽样校验。
