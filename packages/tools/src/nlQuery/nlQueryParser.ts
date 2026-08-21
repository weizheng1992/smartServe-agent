import { METRIC_SEMANTIC_REGISTRY, MetricSemanticResolver } from '../metricRegistry';
import { DimensionResolver } from './dimensionResolver';
import { FilterResolver } from './filterResolver';
import { OrderLimitResolver } from './orderLimitResolver';
import { TextNormalizer } from './textNormalizer';
import { TimeRangeResolver } from './timeRangeResolver';
import type { NLQueryAST } from './types';

/**
 * 🌟 自然语言统一查询语法树解析器 (NLQuery Parser)
 * 职责：编排各个正交解析器，生成结构化查询 AST
 */
export class NLQueryParser {
  public static parse(rawInput: string): NLQueryAST {
    const cleanInput = TextNormalizer.normalize(rawInput);
    const timeRange = TimeRangeResolver.resolve(rawInput);
    const orderLimit = OrderLimitResolver.resolve(rawInput);
    const dimensions = DimensionResolver.resolve(rawInput);
    const filters = FilterResolver.resolve(rawInput);

    // 核心指标消歧与冲突组检测
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
}
