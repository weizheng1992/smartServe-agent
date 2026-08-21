/**
 * 🌟 现代 Agent-NL2SQL 指标元数据注册表 (Metric Semantic Registry v2)
 * 用于：词表匹配 | 向量RAG检索 | LLM约束输出 | SQL模板渲染 | 歧义消歧 | 前端展示 | SaaS鉴权
 */
export type MetricDefinition = {
  // 唯一标识
  key: string;
  // 业务展示名称
  label: string;
  // 完整业务口径（给LLM看，消除口径幻觉）
  description: string;
  // 业务分类，用于RAG过滤、分组
  domain: "sales" | "profit" | "inventory";
  // 来源表，用于做join推导
  sourceTables: string[];

  // ---------------- SQL执行层 ----------------
  /** 指标计算表达式，只写聚合部分，不要写WHERE/GROUP BY */
  expression: string;
  /** 完整SQL模板，变量：{dimensions} {formula} {filters} {timeRange} {limit} {orderBy} */
  sqlTemplate: string;
  /** 业务强制规则，比如分母不能为0、默认过滤条件，写入prompt给LLM */
  businessRules: string[];

  // ---------------- 排序、单位、展示 ----------------
  direction: "ASC" | "DESC";
  unit: "元" | "件" | "%" | "";
  icon: string;

  // ---------------- 语义层（Agent核心） ----------------
  /** 正式别名：系统内部别名 */
  aliases: string[];
  /** 口语同义词：用户自然问句，用于词表命中 */
  synonyms: string[];
  /** 歧义冲突组：同一组词义容易混淆的指标key集合，命中多个触发消歧弹窗/胶囊 */
  conflictGroup?: string[];
  /** 正向样例问句，用于向量入库RAG，给LLM few-shot */
  sampleQueries: string[];

  // ---------------- 工程质量、权限、血缘 ----------------
  // 支持哪些维度做group by
  availableDimensions: string[];
  // 权限标签，做指标访问鉴权
  permissionTag: string;
  // 置信度参考，人工验证过的指标打分0-1
  verifiedConfidence: number;
};

/**
 * 📦 预置商场指标元数据字典 (Standard Mall Semantic Registry)
 */
export const METRIC_SEMANTIC_REGISTRY: Record<string, MetricDefinition> = {
  gmv: {
    key: "gmv",
    label: "总销售额 (GMV)",
    description:
      "统计周期内所有已生效订单的实付销售总流水金额，即 SUM(quantity * price_at_purchase)。不扣除进货成本。",
    domain: "sales",
    sourceTables: ["products", "order_items", "orders"],
    expression: "COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0)::float",
    sqlTemplate: `
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      LEFT JOIN order_items oi ON p.id = oi.product_id
      {filters}
      GROUP BY {groupBy}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    `,
    businessRules: [
      "仅统计有效销售订单，排除已取消未付款订单",
      "单价取下单时快照 price_at_purchase，防止后续商品改价失真",
    ],
    direction: "DESC",
    unit: "元",
    icon: "💰",
    aliases: ["gross_merchandise_volume", "total_sales", "turnover"],
    synonyms: [
      "卖得好",
      "销售额",
      "流水",
      "业绩",
      "最卖钱",
      "成交额",
      "营业额",
      "营业收入",
    ],
    conflictGroup: ["sales_performance_ranking"],
    sampleQueries: [
      "帮我查一下我负责商品里面卖得最好的几个",
      "查看本月销售额最高的商品榜单",
      "哪个商品流水贡献最大",
    ],
    availableDimensions: ["p.id", "p.name", "p.category", "p.manager_id"],
    permissionTag: "sales_viewer",
    verifiedConfidence: 0.98,
  },

  volume: {
    key: "volume",
    label: "出货销量 (件数)",
    description:
      "统计周期内商品实际售出的总件数总量，即 SUM(quantity)。反映商品物理周转频次和爆款热度。",
    domain: "sales",
    sourceTables: ["products", "order_items", "orders"],
    expression: "COALESCE(SUM(oi.quantity), 0)::int",
    sqlTemplate: `
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      LEFT JOIN order_items oi ON p.id = oi.product_id
      {filters}
      GROUP BY {groupBy}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    `,
    businessRules: ["退货件数是否扣减需视售后策略而定，默认统计总出货件数"],
    direction: "DESC",
    unit: "件",
    icon: "📦",
    aliases: ["sales_volume", "total_quantity", "order_units"],
    synonyms: [
      "销量",
      "走量",
      "爆款",
      "出货量",
      "卖得多",
      "单量最多",
      "件数最多",
      "件数",
      "畅销款",
    ],
    conflictGroup: ["sales_performance_ranking"],
    sampleQueries: [
      "哪几款商品出货量最大",
      "查看走量最多的爆款商品",
      "销量排名前三的商品",
    ],
    availableDimensions: ["p.id", "p.name", "p.category", "p.manager_id"],
    permissionTag: "warehouse_operator",
    verifiedConfidence: 0.99,
  },

  gross_profit: {
    key: "gross_profit",
    label: "净毛利润 (收益)",
    description:
      "销售总流水减去进货/物料成本后的净收益，即 SUM(quantity * (price_at_purchase - cost_at_purchase))。",
    domain: "profit",
    sourceTables: ["products", "order_items", "orders"],
    expression:
      "(COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) - COALESCE(SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0)), 0))::float",
    sqlTemplate: `
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      LEFT JOIN order_items oi ON p.id = oi.product_id
      {filters}
      GROUP BY {groupBy}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    `,
    businessRules: [
      "如果 order_items 存在下单成本 cost_at_purchase 则优先使用，否则降级回退至 product 当前 cost_price",
      "毛利可为负数（当贴钱促销时）",
    ],
    direction: "DESC",
    unit: "元",
    icon: "📈",
    aliases: ["profit_amount", "gross_margin_dollars"],
    synonyms: [
      "最赚钱",
      "利润最高",
      "毛利",
      "毛利润",
      "净利润",
      "赚得多",
      "净赚",
      "收益最高",
    ],
    conflictGroup: ["sales_performance_ranking"],
    sampleQueries: [
      "哪几款商品真正最赚钱",
      "净毛利最高的商品排行",
      "刨去进货成本哪款利润最大",
    ],
    availableDimensions: ["p.id", "p.name", "p.category", "p.manager_id"],
    permissionTag: "finance_owner",
    verifiedConfidence: 0.95,
  },

  margin_rate: {
    key: "margin_rate",
    label: "毛利率 (性价比/溢价率)",
    description:
      "净毛利润与总销售额的比率，公式：(毛利润 / NULLIF(总销售额, 0)) * 100。反映单品盈利质量。",
    domain: "profit",
    sourceTables: ["products", "order_items"],
    expression:
      "CASE WHEN SUM(oi.quantity * oi.price_at_purchase) > 0 THEN (((SUM(oi.quantity * oi.price_at_purchase) - SUM(oi.quantity * COALESCE(oi.cost_at_purchase, p.cost_price, 0))) / SUM(oi.quantity * oi.price_at_purchase)) * 100)::float ELSE 0.0 END",
    sqlTemplate: `
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      LEFT JOIN order_items oi ON p.id = oi.product_id
      {filters}
      GROUP BY {groupBy}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    `,
    businessRules: ["必须使用 NULLIF 或 CASE WHEN 规避分母为 0 抛出除零异常"],
    direction: "DESC",
    unit: "%",
    icon: "🎯",
    aliases: ["gross_margin_percentage", "margin_percentage"],
    synonyms: [
      "毛利率",
      "利润率",
      "溢价最高",
      "性价比最高",
      "赚钱效率",
      "回报率",
    ],
    conflictGroup: ["sales_performance_ranking"],
    sampleQueries: ["哪些商品毛利率最高", "溢价空间最大的商品有哪些"],
    availableDimensions: ["p.id", "p.name", "p.category"],
    permissionTag: "finance_owner",
    verifiedConfidence: 0.94,
  },

  stock_risk: {
    key: "stock_risk",
    label: "滞销积压库存",
    expression: "p.stock::int",
    sqlTemplate: `
      SELECT {dimensions}, {formula} AS "metricValue"
      FROM products p
      {filters}
      ORDER BY "metricValue" {direction}
      LIMIT {limit}
    `,
    description:
      "当前仓库在库物理剩余库存件数，用于排查滞销压货与动销缓慢风险。",
    domain: "inventory",
    sourceTables: ["products"],
    businessRules: ["库存预警默认按绝对剩余量降序排列"],
    direction: "DESC",
    unit: "件",
    icon: "⚠️",
    aliases: ["inventory_level", "slow_moving_stock"],
    synonyms: [
      "滞销",
      "积压",
      "卖不出去",
      "库存最多",
      "压货",
      "库存风险",
      "积压款",
      "存货最多",
    ],
    conflictGroup: ["inventory_risk_group"],
    sampleQueries: [
      "仓库里哪些商品积压最多",
      "滞销库存排查",
      "哪些款压货最严重",
    ],
    availableDimensions: ["p.id", "p.name", "p.category"],
    permissionTag: "warehouse_operator",
    verifiedConfidence: 0.96,
  },
};

/**
 * 🌟 智能语义指标匹配器 (Semantic Metric Matcher & Conflict Detector)
 */
export class MetricSemanticResolver {
  /**
   * 自动从自然语言问句中匹配指标，并检测是否命中歧义冲突组
   */
  public static resolve(
    input: string,
    defaultKey = "gmv",
  ): {
    primaryMetric: MetricDefinition;
    isExplicit: boolean;
    matchedSynonym?: string;
    hasAmbiguity: boolean;
    conflictMetrics: MetricDefinition[];
  } {
    const clean = input.trim().toLowerCase();
    const matches: { metric: MetricDefinition; matchedSyn: string }[] = [];

    for (const metric of Object.values(METRIC_SEMANTIC_REGISTRY)) {
      if (clean.includes(metric.key)) {
        matches.push({ metric, matchedSyn: metric.key });
        continue;
      }
      if (clean.includes(metric.label.toLowerCase())) {
        matches.push({ metric, matchedSyn: metric.label });
        continue;
      }
      for (const syn of metric.synonyms) {
        if (clean.includes(syn.toLowerCase())) {
          matches.push({ metric, matchedSyn: syn });
          break;
        }
      }
    }

    // 1. 如果完全没有命中任何具体同义词，采用 Default 兜底（例如用户只说了“查几个商品”）
    if (matches.length === 0) {
      const defaultMetric =
        METRIC_SEMANTIC_REGISTRY[defaultKey] || METRIC_SEMANTIC_REGISTRY.gmv;
      const conflictGroup = defaultMetric.conflictGroup
        ? Object.values(METRIC_SEMANTIC_REGISTRY).filter((m) =>
            m.conflictGroup?.includes(defaultMetric.conflictGroup![0]),
          )
        : [defaultMetric];

      return {
        primaryMetric: defaultMetric,
        isExplicit: false,
        hasAmbiguity: true,
        conflictMetrics: conflictGroup,
      };
    }

    // 2. 如果命中多个，优先选用最长匹配词（例如 "毛利率" 优先于 "毛利"）
    matches.sort((a, b) => b.matchedSyn.length - a.matchedSyn.length);

    const primary = matches[0].metric;
    const isExplicit = true;
    const matchedSynonym = matches[0].matchedSyn;

    const conflictGroupKey = primary.conflictGroup?.[0];
    const conflictMetrics = conflictGroupKey
      ? Object.values(METRIC_SEMANTIC_REGISTRY).filter((m) =>
          m.conflictGroup?.includes(conflictGroupKey),
        )
      : [primary];

    // 仅在泛指模糊提问（如“卖得最好”、“表现最好”）且未指明具体量度（金额/销量/利润/毛利率）时标记歧义
    const genericPhrases = [
      "卖得好",
      "卖得最好",
      "最好",
      "最棒",
      "表现最好",
      "排名靠前",
      "头部商品",
    ];
    const isGeneric = genericPhrases.some((g) => clean.includes(g));
    const isDefinitive =
      clean.includes("金额") ||
      clean.includes("件数") ||
      clean.includes("出货") ||
      clean.includes("销量") ||
      clean.includes("走量") ||
      clean.includes("毛利") ||
      clean.includes("利润") ||
      clean.includes("流水") ||
      clean.includes("营业额") ||
      clean.includes("溢价") ||
      clean.includes("库存") ||
      clean.includes("积压") ||
      clean.includes("滞销");

    const hasAmbiguity =
      isGeneric && !isDefinitive && conflictMetrics.length > 1;

    return {
      primaryMetric: primary,
      isExplicit,
      matchedSynonym,
      hasAmbiguity,
      conflictMetrics,
    };
  }

  /**
   * 动态渲染基于指标元数据的 SQL 语句
   */
  public static renderSql(options: {
    metric: MetricDefinition;
    dimensions: string[];
    groupBy?: string[];
    filters: string;
    limit: number | string;
    direction?: "ASC" | "DESC";
  }): string {
    const { metric, dimensions, groupBy, filters, limit, direction } = options;
    const dimStr = dimensions.join(", ");
    const groupStr = (groupBy || dimensions).join(", ");
    const finalDirection = direction || metric.direction;
    return metric.sqlTemplate
      .replace(/\{dimensions\}/g, dimStr)
      .replace(/\{groupBy\}/g, groupStr)
      .replace(/\{formula\}/g, metric.expression)
      .replace(/\{filters\}/g, filters)
      .replace(/\{direction\}/g, finalDirection)
      .replace(/\{limit\}/g, String(limit));
  }
}
