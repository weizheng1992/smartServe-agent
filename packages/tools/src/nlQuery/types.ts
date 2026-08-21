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
