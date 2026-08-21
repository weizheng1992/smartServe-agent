import type { DimensionResult } from './types';

/**
 * 🌟 维度与分组解析器 (Dimension Resolver)
 * 职责：解耦指标与分组维度，输出 SELECT 字段与 GROUP BY 物理列列表
 */
export class DimensionResolver {
  public static resolve(input: string): DimensionResult {
    const text = input.toLowerCase();

    // 1. 按品类 / 分类分组
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

    // 2. 按运营负责人分组
    if (text.includes('按运营') || text.includes('按负责人') || text.includes('运营维度')) {
      return {
        dimensions: ['p.manager_id'],
        groupBy: ['p.manager_id'],
        primaryDimension: 'manager',
      };
    }

    // 3. 默认：按具体商品粒度
    return {
      dimensions: ['p.id', 'p.name', 'p.category', 'p.price', 'p.cost_price', 'p.stock'],
      groupBy: ['p.id', 'p.name', 'p.category', 'p.price', 'p.cost_price', 'p.stock'],
      primaryDimension: 'product',
    };
  }
}
