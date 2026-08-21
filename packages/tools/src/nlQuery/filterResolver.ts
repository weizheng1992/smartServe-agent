import type { FilterCondition } from './types';

/**
 * 🌟 动态过滤条件解析器 (Filter Resolver)
 * 职责：解析自然语言中的数值阈值过滤（库存、价格等）与类别筛选条件
 */
export class FilterResolver {
  public static resolve(input: string): FilterCondition[] {
    const filters: FilterCondition[] = [];
    const text = input.trim();

    // 1. 库存过滤解析 (如：库存大于500, 库存>=100, 库存低于50)
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

    // 2. 价格过滤解析 (如：价格小于200, 单价大于1000, 价格>=50)
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

    // 3. 品类过滤解析 (如：品类是 shoes, 分类为 零食, 品类等于 shoes)
    const categoryMatch = text.match(/(?:品类|分类)\s*(?:是|为|等于|=|:)\s*([a-zA-Z0-9_一-龥]+)/i);
    if (categoryMatch && categoryMatch[1]) {
      const categoryVal = categoryMatch[1].trim();
      // 防止误匹配词
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
}
