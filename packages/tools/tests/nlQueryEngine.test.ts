import { describe, expect, it } from 'bun:test';
import {
  DimensionResolver,
  FilterResolver,
  NLQueryCompiler,
  NLQueryParser,
  OrderLimitResolver,
  TextNormalizer,
  TimeRangeResolver,
} from '../src/nlQuery';

describe('🧩 Orthogonal NL2SQL Query Parser & Compiler Engine (TDD)', () => {
  // 切片 1: 停用词与虚词语气词清洗
  describe('Slice 1: TextNormalizer (停用词与语气词清洗)', () => {
    it("能够精准剔除 '帮我'、'麻烦看一下'、'给我展示' 等虚词，保留核心语义", () => {
      const raw1 = '麻烦帮我查一下上个月卖得最好的几个商品';
      const clean1 = TextNormalizer.normalize(raw1);
      expect(clean1).not.toContain('麻烦');
      expect(clean1).not.toContain('帮我');
      expect(clean1).not.toContain('查一下');
      expect(clean1).toContain('上个月');
      expect(clean1).toContain('卖得最好');

      const raw2 = '请给我展示一下库存大于500并且利润最高的前3个';
      const clean2 = TextNormalizer.normalize(raw2);
      expect(clean2).not.toContain('请给我展示一下');
      expect(clean2).toContain('库存大于500');
      expect(clean2).toContain('利润最高');
      expect(clean2).toContain('前3个');
    });
  });

  // 切片 2: 独立时间范围解析
  describe('Slice 2: TimeRangeResolver (时序范围解析与 SQL 过滤)', () => {
    it("能够解析 '近 30 天'、'上个月'、'本周'、'近 7 天' 并生成对应 PostgreSQL 时间过滤条件", () => {
      const res30d = TimeRangeResolver.resolve('近30天内哪款商品销量最高');
      expect(res30d).toBeDefined();
      expect(res30d?.key).toBe('last_30d');
      expect(res30d?.sqlFilter).toContain("NOW() - INTERVAL '30 days'");

      const resLastMonth = TimeRangeResolver.resolve('上个月的销售流水是多少');
      expect(resLastMonth).toBeDefined();
      expect(resLastMonth?.key).toBe('last_month');
      expect(resLastMonth?.sqlFilter).toContain("date_trunc('month'");

      const res7d = TimeRangeResolver.resolve('最近7天走量最大的');
      expect(res7d).toBeDefined();
      expect(res7d?.key).toBe('last_7d');
      expect(res7d?.sqlFilter).toContain("NOW() - INTERVAL '7 days'");

      const resNone = TimeRangeResolver.resolve('哪款商品销量最高');
      expect(resNone).toBeUndefined();
    });
  });

  // 切片 3: 排序方向改写与 TopN 解析
  describe('Slice 3: OrderLimitResolver (排序改写与 TopN 提取)', () => {
    it("能够解析用户显式指定的 '最低'、'倒数'、'最差' 并覆盖指标默认排序方向 (ASC)", () => {
      const resMin = OrderLimitResolver.resolve('看销售额最低的前5个');
      expect(resMin.directionOverride).toBe('ASC');
      expect(resMin.limit).toBe(5);

      const resBottom = OrderLimitResolver.resolve('倒数第10名');
      expect(resBottom.directionOverride).toBe('ASC');
      expect(resBottom.limit).toBe(10);
    });

    it("能够解析默认或正向 topN (如 '前 3 名', 'Top 8')", () => {
      const resTop = OrderLimitResolver.resolve('排名前3的爆款');
      expect(resTop.directionOverride).toBe('DESC');
      expect(resTop.limit).toBe(3);

      const resDefault = OrderLimitResolver.resolve('卖得最好的商品');
      expect(resDefault.limit).toBe(5); // 默认 5
      expect(resDefault.directionOverride).toBeUndefined(); // 未指定时遵循指标自身默认
    });
  });

  // 切片 4: 维度与分组识别
  describe('Slice 4: DimensionResolver (维度分组解析)', () => {
    it("能够解析 '按品类' / '按分类' / '按商品' 维度并输出正确的 dimensions 和 groupBy", () => {
      const resCategory = DimensionResolver.resolve('按品类统计总销售额');
      expect(resCategory.dimensions).toEqual(['p.category']);
      expect(resCategory.groupBy).toEqual(['p.category']);

      const resProduct = DimensionResolver.resolve('按商品看利润');
      expect(resProduct.dimensions).toContain('p.id');
      expect(resProduct.dimensions).toContain('p.name');
      expect(resProduct.groupBy).toContain('p.id');

      // 默认按商品维度
      const resDefault = DimensionResolver.resolve('哪个最赚钱');
      expect(resDefault.dimensions).toContain('p.id');
      expect(resDefault.dimensions).toContain('p.name');
    });
  });

  // 切片 5: 动态条件与数值过滤
  describe('Slice 5: FilterResolver (数值与品类过滤条件解析)', () => {
    it("能够解析 '库存大于 500'、'价格低于 200'、'品类是鞋类' 等条件并转换为 SQL 过滤表达式", () => {
      const resFilters1 = FilterResolver.resolve('库存大于500并且价格小于200的商品');
      expect(resFilters1.length).toBe(2);

      const stockFilter = resFilters1.find((f) => f.field === 'p.stock');
      expect(stockFilter).toBeDefined();
      expect(stockFilter?.op).toBe('>');
      expect(stockFilter?.value).toBe(500);
      expect(stockFilter?.sqlClause).toBe('p.stock > 500');

      const priceFilter = resFilters1.find((f) => f.field === 'p.price');
      expect(priceFilter).toBeDefined();
      expect(priceFilter?.op).toBe('<');
      expect(priceFilter?.value).toBe(200);
      expect(priceFilter?.sqlClause).toBe('p.price < 200');

      const resFilters2 = FilterResolver.resolve('品类是 shoes 且库存>=100');
      const catFilter = resFilters2.find((f) => f.field === 'p.category');
      expect(catFilter).toBeDefined();
      expect(catFilter?.op).toBe('=');
      expect(catFilter?.value).toBe('shoes');
    });
  });

  // 切片 6: 端到端 NLQueryParser 与 NLQueryCompiler
  describe('Slice 6: NLQueryParser & NLQueryCompiler (端到端 AST 解析与编译)', () => {
    it('能够将复杂综合问句一键解析为 AST 并编译为无注入的真实 PostgreSQL 语句', () => {
      const complexQuery = '麻烦帮我查一下近30天库存大于100的商品里面，按品类看销售额最高的前3个';
      const ast = NLQueryParser.parse(complexQuery);

      expect(ast.metricKey).toBe('gmv');
      expect(ast.timeRange?.key).toBe('last_30d');
      expect(ast.limit).toBe(3);
      expect(ast.dimensions).toEqual(['p.category']);
      expect(ast.filters.some((f) => f.field === 'p.stock' && f.op === '>')).toBe(true);

      // 编译为 SQL
      const sql = NLQueryCompiler.compile({
        ast,
        businessId: 'nike',
        managerId: 'mgr_wei',
      });

      expect(sql).toContain('SELECT p.category');
      expect(sql).toContain('GROUP BY p.category');
      expect(sql).toContain("p.business_id = 'nike'");
      expect(sql).toContain("p.manager_id = 'mgr_wei'");
      expect(sql).toContain('p.stock > 100');
      expect(sql).toContain("NOW() - INTERVAL '30 days'");
      expect(sql).toContain('LIMIT 3');
    });
  });
});
