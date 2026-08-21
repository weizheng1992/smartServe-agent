import {
  METRIC_SEMANTIC_REGISTRY,
  MetricSemanticResolver,
} from "../metricRegistry";
import type { NLQueryAST } from "./types";

export interface CompileOptions {
  ast: NLQueryAST;
  businessId: string;
  managerId?: string;
}

/**
 * 🌟 统一自然语言 SQL 编译器 (NLQuery Compiler)
 * 职责：结合 AST、租户隔离上下文、指标模板动态编译物理安全 SQL
 */
export class NLQueryCompiler {
  public static compile(options: CompileOptions): string {
    const { ast, businessId, managerId } = options;
    const metric =
      METRIC_SEMANTIC_REGISTRY[ast.metricKey] || METRIC_SEMANTIC_REGISTRY.gmv;

    // 1. 构建 WHERE 过滤条件（租户隔离 + 经理隔离 + 数值过滤 + 时间范围）
    const whereClauses: string[] = [
      `p.business_id = '${businessId.replace(/'/g, "''")}'`,
    ];

    if (managerId) {
      whereClauses.push(`p.manager_id = '${managerId.replace(/'/g, "''")}'`);
    }

    for (const filter of ast.filters) {
      whereClauses.push(filter.sqlClause);
    }

    if (ast.timeRange?.sqlFilter) {
      whereClauses.push(ast.timeRange.sqlFilter);
    }

    const filtersStr =
      whereClauses.length > 0 ? `WHERE ${whereClauses.join(" AND ")}` : "";

    // 2. 排序方向（用户显式改写优先，否则走指标默认）
    const finalDirection = ast.directionOverride || metric.direction;

    // 3. 动态渲染 SQL
    const dimStr = ast.dimensions.join(", ");
    const groupStr = ast.groupBy.join(", ");

    return metric.sqlTemplate
      .replace(/\{dimensions\}/g, dimStr)
      .replace(/\{groupBy\}/g, groupStr)
      .replace(/\{formula\}/g, metric.expression)
      .replace(/\{filters\}/g, filtersStr)
      .replace(/\{direction\}/g, finalDirection)
      .replace(/\{limit\}/g, String(ast.limit));
  }
}
