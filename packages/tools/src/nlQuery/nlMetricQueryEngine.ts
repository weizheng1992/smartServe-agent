import { METRIC_SEMANTIC_REGISTRY, MetricSemanticResolver } from '../metricRegistry';

export interface TimeRangeResult {
  key: 'today' | 'last_7d' | 'last_30d' | 'last_month' | 'this_year' | 'custom';
  label: string;
  sqlFilter: string;
}

export interface FilterCondition {
  field: string;
  op: '>' | '>=' | '<' | '<=' | '=' | '!=' | 'LIKE';
  value: string | number;
  sqlClause: string;
}

export interface DimensionResult {
  dimensions: string[];
  groupBy: string[];
  primaryDimension: 'product' | 'category' | 'manager';
}

export interface OrderLimitResult {
  directionOverride?: 'ASC' | 'DESC';
  limit: number;
}

export interface CompiledSQL {
  text: string;
  values: unknown[];
}

export interface NLQueryAST {
  rawInput: string;
  cleanInput: string;
  metricKey: string;
  timeRange?: TimeRangeResult;
  filters: FilterCondition[];
  dimensions: string[];
  groupBy: string[];
  directionOverride?: 'ASC' | 'DESC';
  limit: number;
  hasAmbiguity: boolean;
  conflictGroup?: string[];
}

export interface CompileOptions {
  ast: NLQueryAST;
  businessId: string;
  managerId?: string;
}

/**
 * 🌟 NLMetricQueryEngine 自然语言指标统一查询编译深模块 (Deep Module)
 * 职责：
 * 1. 停用词/虚词语气词清洗 (Text Normalization)
 * 2. 正交时间范围切分与 PostgreSQL WHERE 子句生成 (Time Range Resolving)
 * 3. 排序方向改写与 TopN 限制解析 (Order & Limit Resolving)
 * 4. 统计粒度维度与 GROUP BY 列映射 (Dimension & GroupBy Resolving)
 * 5. 动态数值与品类过滤条件提取 (Dynamic Filters Resolving)
 * 6. 端到端 AST 构建与物理安全 SQL 编译 (AST Parsing & SQL Compilation)
 */
export class NLMetricQueryEngine {
  private static readonly STOP_WORDS: RegExp[] = [
    /^(麻烦|请问|请|能否|帮我|麻烦帮我|请给我|给我|帮我看下|帮我查一下|查一下|看一下|查询|展示一下|给我展示一下|对比看看|看下|看看)\s*/gi,
    /(麻烦|请问|请|能否|帮我|给我展示一下|展示一下|查一下|看一下|看下|看看|里面|当中|之中)/gi,
  ];

  /**
   * 1. 问句语气词与虚词预处理清洗
   */
  public static normalize(input: string): string {
    if (!input) return '';
    let text = input.trim();
    text = text.replace(/[？?！!，,。；;]/g, ' ');
    for (const pattern of this.STOP_WORDS) {
      text = text.replace(pattern, ' ');
    }
    return text.replace(/\s+/g, ' ').trim();
  }

  /**
   * 2. 独立时序时间范围解析
   */
  public static resolveTimeRange(input: string): TimeRangeResult | undefined {
    const text = input.toLowerCase();

    if (
      text.includes('近30天') ||
      text.includes('最近30天') ||
      text.includes('过去30天') ||
      text.includes('近一个月') ||
      text.includes('最近一个月')
    ) {
      return {
        key: 'last_30d',
        label: '近 30 天',
        sqlFilter: "o.created_at >= NOW() - INTERVAL '30 days'",
      };
    }

    if (text.includes('上个月') || text.includes('上月') || text.includes('上个自然月')) {
      return {
        key: 'last_month',
        label: '上个月',
        sqlFilter:
          "o.created_at >= date_trunc('month', NOW() - INTERVAL '1 month') AND o.created_at < date_trunc('month', NOW())",
      };
    }

    if (
      text.includes('近7天') ||
      text.includes('最近7天') ||
      text.includes('过去7天') ||
      text.includes('近一周') ||
      text.includes('最近一周')
    ) {
      return {
        key: 'last_7d',
        label: '近 7 天',
        sqlFilter: "o.created_at >= NOW() - INTERVAL '7 days'",
      };
    }

    if (text.includes('今天') || text.includes('当日') || text.includes('今日')) {
      return {
        key: 'today',
        label: '今日',
        sqlFilter: "o.created_at >= date_trunc('day', NOW())",
      };
    }

    if (text.includes('今年') || text.includes('本年度') || text.includes('年内')) {
      return {
        key: 'this_year',
        label: '今年',
        sqlFilter: "o.created_at >= date_trunc('year', NOW())",
      };
    }

    return undefined;
  }

  /**
   * 3. 排序方向与 TopN 解析
   */
  public static resolveOrderLimit(input: string): OrderLimitResult {
    let directionOverride: 'ASC' | 'DESC' | undefined;
    let limit = 5;

    const text = input.toLowerCase();

    if (
      text.includes('最低') ||
      text.includes('倒数') ||
      text.includes('最差') ||
      text.includes('最少') ||
      text.includes('最慢') ||
      text.includes('最小') ||
      text.includes('升序') ||
      text.includes('从小到大') ||
      text.includes('从低到高')
    ) {
      directionOverride = 'ASC';
    } else if (
      text.includes('最高') ||
      text.includes('最多') ||
      text.includes('降序') ||
      text.includes('从大到小') ||
      text.includes('从高到低') ||
      text.includes('排名前')
    ) {
      directionOverride = 'DESC';
    }

    const limitPatterns = [/(?:top|前|排名前|倒数第?|最后)\s*(\d+)/i, /(\d+)\s*(?:个|名|款|件|条)/i];

    for (const pattern of limitPatterns) {
      const match = text.match(pattern);
      if (match && match[1]) {
        const parsed = Number.parseInt(match[1], 10);
        if (!Number.isNaN(parsed) && parsed > 0) {
          limit = Math.min(parsed, 50);
          break;
        }
      }
    }

    return {
      directionOverride,
      limit,
    };
  }

  /**
   * 4. 维度与分组解析
   */
  public static resolveDimension(input: string): DimensionResult {
    const text = input.toLowerCase();

    if (
      text.includes('按品类') ||
      text.includes('按分类') ||
      text.includes('品类维度') ||
      text.includes('各个品类') ||
      text.includes('各分类')
    ) {
      return {
        dimensions: ['p.category'],
        groupBy: ['p.category'],
        primaryDimension: 'category',
      };
    }

    if (text.includes('按运营') || text.includes('按负责人') || text.includes('运营维度')) {
      return {
        dimensions: ['p.manager_id'],
        groupBy: ['p.manager_id'],
        primaryDimension: 'manager',
      };
    }

    return {
      dimensions: ['p.id', 'p.name', 'p.category', 'p.price', 'p.cost_price', 'p.stock'],
      groupBy: ['p.id', 'p.name', 'p.category', 'p.price', 'p.cost_price', 'p.stock'],
      primaryDimension: 'product',
    };
  }

  /**
   * 5. 动态过滤条件解析
   */
  public static resolveFilters(input: string): FilterCondition[] {
    const filters: FilterCondition[] = [];
    const text = input.trim();

    const stockMatch = text.match(
      /库存\s*(大于等于|高于等于|>=|<=|小于等于|低于等于|>|<|大于|高于|小于|低于|=)\s*(\d+)/i,
    );
    if (stockMatch) {
      const opRaw = stockMatch[1];
      const val = Number.parseInt(stockMatch[2], 10);
      const op = this.normalizeOperator(opRaw);
      filters.push({
        field: 'p.stock',
        op,
        value: val,
        sqlClause: `p.stock ${op} ${val}`,
      });
    }

    const priceMatch = text.match(
      /(?:价格|单价|售价)\s*(大于等于|高于等于|>=|<=|小于等于|低于等于|>|<|大于|高于|小于|低于|=)\s*(\d+(?:\.\d+)?)/i,
    );
    if (priceMatch) {
      const opRaw = priceMatch[1];
      const val = Number.parseFloat(priceMatch[2]);
      const op = this.normalizeOperator(opRaw);
      filters.push({
        field: 'p.price',
        op,
        value: val,
        sqlClause: `p.price ${op} ${val}`,
      });
    }

    const categoryMatch = text.match(/(?:品类|分类)\s*(?:是|为|等于|=|:)\s*([a-zA-Z0-9_一-龥]+)/i);
    if (categoryMatch && categoryMatch[1]) {
      const categoryVal = categoryMatch[1].trim();
      if (!['看', '统计', '维度'].includes(categoryVal)) {
        filters.push({
          field: 'p.category',
          op: '=',
          value: categoryVal,
          sqlClause: `p.category = '${categoryVal.replace(/'/g, "''")}'`,
        });
      }
    }

    return filters;
  }

  private static normalizeOperator(raw: string): '>' | '>=' | '<' | '<=' | '=' | '!=' {
    if (raw === '>=' || raw.includes('大于等于') || raw.includes('高于等于')) return '>=';
    if (raw === '<=' || raw.includes('小于等于') || raw.includes('低于等于')) return '<=';
    if (raw === '>' || raw.includes('大于') || raw.includes('高于')) return '>';
    if (raw === '<' || raw.includes('小于') || raw.includes('低于')) return '<';
    return '=';
  }

  /**
   * 6. 端到端 AST 语法树解析
   */
  public static parse(rawInput: string): NLQueryAST {
    const cleanInput = this.normalize(rawInput);
    const timeRange = this.resolveTimeRange(rawInput);
    const orderLimit = this.resolveOrderLimit(rawInput);
    const dimensions = this.resolveDimension(rawInput);
    const filters = this.resolveFilters(rawInput);

    const metricRes = MetricSemanticResolver.resolve(cleanInput || rawInput);

    return {
      rawInput,
      cleanInput,
      metricKey: metricRes.primaryMetric.key,
      timeRange,
      filters,
      dimensions: dimensions.dimensions,
      groupBy: dimensions.groupBy,
      directionOverride: orderLimit.directionOverride,
      limit: orderLimit.limit,
      hasAmbiguity: metricRes.hasAmbiguity,
      conflictGroup: metricRes.primaryMetric.conflictGroup,
    };
  }

  /**
   * 7. 动态安全参数化 SQL 编译 (Parameterized Prepared Statement Compilation)
   */
  public static compile(options: CompileOptions): CompiledSQL {
    const { ast, businessId, managerId } = options;
    const metric = METRIC_SEMANTIC_REGISTRY[ast.metricKey] || METRIC_SEMANTIC_REGISTRY.gmv;

    const values: unknown[] = [];
    const addParam = (val: unknown): string => {
      values.push(val);
      return `$${values.length}`;
    };

    const whereClauses: string[] = [`p.business_id = ${addParam(businessId)}`];

    if (managerId) {
      whereClauses.push(`p.manager_id = ${addParam(managerId)}`);
    }

    const ALLOWED_FIELDS = new Set([
      'p.stock',
      'p.price',
      'p.category',
      'p.cost_price',
      'p.id',
      'p.name',
      'p.manager_id',
      'p.business_id',
    ]);
    const ALLOWED_OPS = new Set(['>', '>=', '<', '<=', '=', '!=']);

    for (const filter of ast.filters) {
      const op = ALLOWED_OPS.has(filter.op) ? filter.op : '=';
      const field = ALLOWED_FIELDS.has(filter.field) ? filter.field : 'p.id';
      whereClauses.push(`${field} ${op} ${addParam(filter.value)}`);
    }

    if (ast.timeRange?.sqlFilter) {
      whereClauses.push(ast.timeRange.sqlFilter);
    }

    const filtersStr = whereClauses.length > 0 ? `WHERE ${whereClauses.join(' AND ')}` : '';
    const finalDirection =
      ast.directionOverride === 'ASC' || ast.directionOverride === 'DESC' ? ast.directionOverride : metric.direction;
    const dimStr = ast.dimensions.join(', ');
    const groupStr = ast.groupBy.join(', ');
    const safeLimit = Math.min(Math.max(1, ast.limit || 5), 50);

    const text = metric.sqlTemplate
      .replace(/\{dimensions\}/g, dimStr)
      .replace(/\{groupBy\}/g, groupStr)
      .replace(/\{formula\}/g, metric.expression)
      .replace(/\{filters\}/g, filtersStr)
      .replace(/\{direction\}/g, finalDirection)
      .replace(/\{limit\}/g, addParam(safeLimit))
      .trim();

    return {
      text,
      values,
    };
  }
}

// 兼容别名导出
export const TextNormalizer = {
  normalize: (input: string) => NLMetricQueryEngine.normalize(input),
};

export const TimeRangeResolver = {
  resolve: (input: string) => NLMetricQueryEngine.resolveTimeRange(input),
};

export const OrderLimitResolver = {
  resolve: (input: string) => NLMetricQueryEngine.resolveOrderLimit(input),
};

export const DimensionResolver = {
  resolve: (input: string) => NLMetricQueryEngine.resolveDimension(input),
};

export const FilterResolver = {
  resolve: (input: string) => NLMetricQueryEngine.resolveFilters(input),
};

export const NLQueryParser = {
  parse: (rawInput: string) => NLMetricQueryEngine.parse(rawInput),
};

export const NLQueryCompiler = {
  compile: (options: CompileOptions) => NLMetricQueryEngine.compile(options),
};
