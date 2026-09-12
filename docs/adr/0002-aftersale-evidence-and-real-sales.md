# ADR-0002: 售后凭证落库 + 排行真销量源 + 热销文案解禁

- 日期: 2026-09-12
- 状态: 设计定案(grill-with-docs 两轮八问逐项裁决),随轮实现
- 关联: ADR-0001(场景化快捷回复)、CHANGELOG 2.6.8(商户货架无销量列,严禁合成假热度——本 ADR 部分解除该禁令的前提是真数据到位)

## 背景

2.6.14 收尾留档三项同根源遗留:①照片上传后凭证不落售后工单(`apply_after_sale` 无凭证字段,人工审批员看不到图);②`queryProductRanking` 数据源错位(engine 本地 5 行演示表 + manager_id 过滤,恒诚实空);③「卖得好/热销」文案因无销量数据被 2.6.8 铁律禁止。三者共享根源:**数据不在该在的地方**。

用户授权商户目录扩容(多加分类、多加产品),顺带把 2.6.14 时点名的「衬衫」补进真实货架。

## 事实基础(2026-09-12 查证)

1. `apply_after_sale` 真实落库 agent_platform:`after_sale_tickets`(无任何附件列)+ `after_sale_logs`;工具 schema 无图片参数;`OrderRefundSkill` 技能快轨可拿到 `context.imageUrls`,但从未使用。
2. 原始图片 URL 已两处持久:`messages.image_urls` JSONB(网关写)与本轮 `state["image_urls"]`;damage_assessment 只带第一张的 `imageUrl`。
3. **真销量数据存在**:`merchant_order_items`(spu_id/sku_code/quantity/price)× `merchant_orders`(状态 PAID/SHIPPED/DELIVERED/REFUNDED)可聚合真销量/真 GMV;但商户库**无成本价列**,毛利/毛利率无法诚实计算。
4. 前端 `RankedProductItem` 的销售字段早已可选(2.6.12 白屏修复),缺省降级「—」,排行换源零前端改动。
5. 建表机制 Alembic(services/engine-py/alembic)。

## 决策(用户逐项裁决「按照推荐」+ 新授权)

1. **Q1 凭证结构化落票**:`after_sale_tickets` 加 `evidence_urls JSONB` 列;`applyAfterSale` 工具 schema 加 `evidenceImageUrls` 参数;注入走**程序化**严禁指望 LLM 抄 URL——技能快轨从 `context.imageUrls` 注入,LLM 工具路径在 executor 层检测「调 applyAfterSale 且无凭证参数且本轮有图」时程序化补注;HITL 审批 `action_payload` 自动携带,人工审批员可见。
2. **Q2 凭证范围只带本轮**:仅 `state.image_urls`(≤3 张);会话历史回溯留二期。
3. **Q3 排行换商户库真源**:`merchant_order_items × merchant_orders`(排除 REFUNDED/CANCELLED)按 SPU 聚合真销量/真 GMV;库存风险用 `merchant_skus.stock`;**gross_profit/margin_rate 两指标整体移除**(商户库无成本价,算不了就不提供);manager_id/businessId 过滤摘除(单商户现实,全租户统一路由先例)。
4. **Q4 热销全套升级**:排行修源 + 品类 chips 首位「🔥 热销商品」入口(点击走真销量排行)+ 排行卡出真数据;「热销」文案解禁——**前提是背后有真实聚合**,2.6.8 禁令自本 ADR 起改为「严禁无真数据支撑的热度文案」。
5. **Q5/Q8 演示数据扩充**:商户目录 6→9 品类(新增 衬衫/配饰/运动配件)、18→30 SPU、62→约 100 SKU;历史订单扩到约 30 笔/60 行明细,覆盖约 2/3 SPU(头部 4~8 件、腰部 1~3 件、长尾零销量),状态以 PAID/SHIPPED/DELIVERED 为主、少量 REFUNDED(顺带真实验证「排除退款单」聚合),日期散布 60 天,seed 注明「演示环境历史交易,聚合永远真算」。
6. **Q6 新品类**:衬衫(用户最初点名)、配饰、运动配件,每 SPU 带 SKU 矩阵/真实感文案。
7. **Q7 chips 上限 8**:热销入口置顶,其余品类按在售款数降序补足。

## 一并定夺的实现细节

- 排行卡下方指标消歧胶囊组 5→3(GMV/销量/滞销)——挂着算不了的毛利指标就是死按钮。
- 热销入口点击文本「有什么热销商品」,路由以测试与实弹钉死。
- 管理端审批页一期透出含凭证 URL 的 JSON 载荷,美化渲染二期。
- README/CHANGELOG 目录计数同步;商户 seed 行数断言随新规模改写。

## 后果

- 「热销/卖得好」从绝对禁令改为**数据条件禁令**:有真实聚合才可说,聚合为零时诚实空。
- 排行输出条目不再含 costPrice/grossProfit/marginRate(前端已可选渲染,零改动)。
- `after_sale_tickets` 语义升级:审批与售后追溯可凭图。
- 引擎本地 products 表的排行路径退役;本地演示单不再参与任何排行。

## 验证(2026-09-12 实现后回填,如实)

- engine pytest **484 passed**(2.6.14 基线 465 + 新增 19:凭证落库 7(含诚实失败)/ 排行真源 8(含 JOIN 扇出钉死)/ 快路径路由 3 / 场景快捷区净增 1);gateway 121 passed;ruff 双服务干净;Alembic 0009/0010 已应用生产库。
- 实弹(网关重启 + 商户库重播种 30 单/日期散布 2026-07-17~09-10):
  - 「按销量查一下热销商品排行」→ 真排行卡:T恤 7 件 No.1、冲锋衣 5 件(GMV 6,495 = 5×1299),退款单已排除,统计口径胶囊组 3 键;
  - 实弹抓出并修复三个缺陷:①排行 JOIN 扇出(1 SPU×N SKU×M 明细笛卡尔放大,5 件卖成 30 件——密封测试补双 SKU 钉死);②`after_sale_tickets.order_id` 外键指向本地 orders,商户真单售后**从未真正落库**且异常被吞成假 `success:True`(0010 去 FK + 诚实报错,真 DB 直调验证 evidence_urls 落库);③导购推荐卡冒充排行卡(rankingMetric=recommendation + 「热销推荐」标签 + 编造 metricScore)触发统计口径胶囊组——改「为您推荐/店长精选」、拆编造分数、消歧组只认真源指标;
  - 「看看衬衫有什么商品」→ 新品类 4 款真实命中(皮肤衬衫库存 98 = 三 SKU 之和);
  - 带图售后 → executor 注入实弹命中:processRefund 审批载荷 args 含 `evidenceImageUrls`(旧审批行天然对照无凭证);快捷区热销入口置顶 + 品类按款数降序上限 8。
- 实际规模(与 spec「约数」对照,如实):9 品类 / 30 SPU / 92 SKU(spec 约 100);30 单 / 47 行明细 / 51 件 / 覆盖 17/30 SPU / REFUNDED 2 单(spec 约 60 行,47 略低但分布达标)。
