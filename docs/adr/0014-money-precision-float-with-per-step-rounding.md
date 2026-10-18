# 0014 — 金额精度:float + 逐步 round 即精度方案,Decimal/整数分不采纳

状态:已接受(2026-10-18)
背景:全量审查盲区扫描(critic#2)标记「NUMERIC(10,2) 全程经 Python float 往返、全仓无 Decimal」为精度盲区,提议 Decimal 化或整数分记账。

## 决策

商户金额计算**维持 float + 每步 round(…, 2)** 的现行纪律,不引入 Decimal 也不改整数分。理由:

1. **域本身是 2 位小数**:价格/优惠/门槛全部 2-dp,引擎(`analytics/promotion_engine.py`)与结算核(`merchant_domain._commit_order`)在每个算价步(优惠、余额钳制、合计、实付)都 round 到分 —— 浮点误差到不了第 3 位小数,落账/信封值恒为精确 2-dp;
2. **存储精确**:PG `NUMERIC(10,2)`,DB 侧无浮点;
3. **线上格式不可变**:JSON 无 decimal,JS `Number` 本就是 float —— 三种方案下 wire 完全相同,收益只在 Python 内部;
4. **改造成本 > 病痛**:Decimal 化需动 2026-10-18 刚落地的结算核(`_commit_order`)与 engine 促销引擎 + 全部金额测试重验;整数分还要在每个 DB/JSON 边界 ×100/÷100(换算点最多、最易错)。核验时**无任何一例实弹分位 bug**(该发现源自盲区扫描,非实弹)。

## 升级条件

出现**真实分位 bug 实弹**(对账差 1 分、半分边界错分且可复现)时,升级为 Decimal(quantize 0.01)方案,改造自结算核 `_commit_order` 与 `promotion_engine` 起。在此之前,架构审查/盲区扫描**不再将 float 金额列为待修项**。

## 影响

- `merchant_domain._commit_order` / `promotion_engine` 的每步 round 语义是**精度方案的一部分**,重构时不得以「顺手清理」为由移除;
- 遥测 `cost_usd`(非商户金额,按模型单价换算)不适用本决策,亦不在 Decimal 化范围。
