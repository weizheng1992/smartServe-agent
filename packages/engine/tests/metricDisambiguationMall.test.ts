import { describe, expect, it } from "bun:test";
import {
  METRIC_SEMANTIC_REGISTRY,
  MetricSemanticResolver,
  OrderDomainService,
} from "tools";
import { CardSynthesizer } from "../src/cards/cardSynthesizer";
import {
  PRODUCT_RANKING_METRIC_SLOT,
  SlotDisambiguationEngine,
} from "../src/disambiguation/slotDisambiguationEngine";

describe("🏪 Mall Semantic Metric Registry & Disambiguation Suite", () => {
  it("MetricSemanticRegistry: 注册表规范与口径完备性校验", () => {
    expect(METRIC_SEMANTIC_REGISTRY.gmv).toBeDefined();
    expect(METRIC_SEMANTIC_REGISTRY.volume).toBeDefined();
    expect(METRIC_SEMANTIC_REGISTRY.gross_profit).toBeDefined();
    expect(METRIC_SEMANTIC_REGISTRY.margin_rate).toBeDefined();
    expect(METRIC_SEMANTIC_REGISTRY.stock_risk).toBeDefined();

    // 检查核心属性符合 v2 契约
    const gmv = METRIC_SEMANTIC_REGISTRY.gmv;
    expect(gmv.domain).toBe("sales");
    expect(gmv.expression).toContain("SUM(oi.quantity * oi.price_at_purchase)");
    expect(gmv.sqlTemplate).toContain("{formula}");
    expect(gmv.conflictGroup).toContain("sales_performance_ranking");
    expect(gmv.synonyms.length).toBeGreaterThan(3);
  });

  it("MetricSemanticResolver: 模糊自然语言解析与冲突组消歧检测", () => {
    // 1. 模糊问句：命中冲突组并提示消歧
    const res1 = MetricSemanticResolver.resolve(
      "帮我查一下我负责商品里面卖得最好的几个",
    );
    expect(res1.primaryMetric.key).toBe("gmv");
    expect(res1.hasAmbiguity).toBe(true);
    expect(res1.conflictMetrics.length).toBeGreaterThanOrEqual(3);
    expect(res1.conflictMetrics.map((m) => m.key)).toContain("gross_profit");
    expect(res1.conflictMetrics.map((m) => m.key)).toContain("volume");

    // 2. 明确利润问句
    const res2 = MetricSemanticResolver.resolve("哪几款商品最赚钱，净利润最高");
    expect(res2.primaryMetric.key).toBe("gross_profit");
    expect(res2.isExplicit).toBe(true);

    // 3. 明确走量问句
    const res3 = MetricSemanticResolver.resolve("出货量走量最多的爆款是哪件");
    expect(res3.primaryMetric.key).toBe("volume");
    expect(res3.isExplicit).toBe(true);

    // 4. 滞销库存预警问句
    const res4 =
      MetricSemanticResolver.resolve("仓库里积压最多、滞销的是哪几款");
    expect(res4.primaryMetric.key).toBe("stock_risk");
    expect(res4.isExplicit).toBe(true);
  });

  it("SlotDisambiguationEngine: 声明式槽位解析与动态快捷胶囊生成", () => {
    const res = SlotDisambiguationEngine.resolveSlot(
      "查查卖得最好的",
      PRODUCT_RANKING_METRIC_SLOT,
    );

    expect(res.resolvedValue).toBe("gmv");
    expect(res.quickReplies).toBeDefined();
    expect(res.quickReplies?.options.length).toBe(3);
    expect(
      res.quickReplies?.options.some((o) => o.label.includes("出货销量")),
    ).toBe(true);
    expect(
      res.quickReplies?.options.some((o) => o.label.includes("净毛利润")),
    ).toBe(true);
  });

  it("OrderDomainService.queryProductRanking: 物理 SQL 动态聚合与多维排行准确度", async () => {
    // 1. 测试 GMV (销售额) 排序 (Nike 专营店)
    const gmvRes = await OrderDomainService.queryProductRanking({
      rankingMetric: "gmv",
      businessId: "nike",
      managerOnly: false,
      limit: 5,
    });
    expect(gmvRes.success).toBe(true);
    const gmvProducts = gmvRes.products as any[];
    expect(gmvProducts.length).toBeGreaterThan(0);
    // 顶级跑鞋 / 飞马跑鞋 流水最高
    expect(gmvProducts[0].totalGmv).toBeGreaterThanOrEqual(
      gmvProducts[1].totalGmv,
    );

    // 2. 测试 Volume (出货销量) 排序 -> 长筒袜应该是第 1 名 (150 件)
    const volumeRes = await OrderDomainService.queryProductRanking({
      rankingMetric: "volume",
      businessId: "nike",
      managerOnly: false,
      limit: 5,
    });
    expect(volumeRes.success).toBe(true);
    const volumeProducts = volumeRes.products as any[];
    expect(volumeProducts[0].productId).toBe("prod_nike_socks_pack");
    expect(volumeProducts[0].totalVolume).toBe(150);

    // 3. 测试 Gross Profit (净毛利润) 排序 -> Vaporfly 顶级竞速鞋应该是第 1 名 (利润 19,800 元)
    const profitRes = await OrderDomainService.queryProductRanking({
      rankingMetric: "gross_profit",
      businessId: "nike",
      managerOnly: false,
      limit: 5,
    });
    expect(profitRes.success).toBe(true);
    const profitProducts = profitRes.products as any[];
    expect(profitProducts[0].productId).toBe("prod_nike_vaporfly");
    expect(profitProducts[0].grossProfit).toBe(19800);
  });

  it("CardSynthesizer: 自动合成 product_ranking 富卡片与消歧胶囊", () => {
    const mockTaskPlan = {
      subtasks: [
        {
          id: "step_ranking",
          description: "Query mall product ranking",
          status: "completed" as const,
          result: {
            rankingMetric: "gmv",
            metricLabel: "总销售额 (GMV)",
            metricUnit: "元",
            itemCount: 2,
            summary: "已为您生成商品销售排行榜",
            products: [
              {
                rank: 1,
                productId: "prod_nike_vaporfly",
                name: "Nike ZoomX Vaporfly 3 顶级竞速跑鞋",
                category: "shoes",
                price: 1599,
                totalVolume: 18,
                totalGmv: 28782,
                grossProfit: 19800,
                marginRate: "68.8%",
                metricScore: 28782,
                metricDisplay: "28,782 元",
              },
            ],
          },
        },
      ],
    };

    const cards = CardSynthesizer.synthesizeCards({
      taskPlan: mockTaskPlan as any,
    });

    const rankingCard = cards.find((c) => c.type === "product_ranking");
    expect(rankingCard).toBeDefined();
    expect(rankingCard?.data.metricLabel).toBe("总销售额 (GMV)");
    expect((rankingCard?.data as any).products.length).toBe(1);

    const quickReplies = cards.find((c) => c.type === "quick_replies");
    expect(quickReplies).toBeDefined();
    expect(
      quickReplies?.data.options.some((o) => o.label.includes("出货销量")),
    ).toBe(true);
    expect(
      quickReplies?.data.options.some((o) => o.label.includes("净毛利润")),
    ).toBe(true);
  });
});
