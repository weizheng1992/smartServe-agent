import type { TimeRangeResult } from './types';

/**
 * 🌟 独立时序时间范围解析器 (Time Range Resolver)
 * 职责：解耦指标与时序词，独立输出 timeRange Key 与 PostgreSQL 物理 WHERE 时间过滤子句
 */
export class TimeRangeResolver {
  public static resolve(input: string): TimeRangeResult | undefined {
    const text = input.toLowerCase();

    // 1. 近 30 天 / 最近一个月
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

    // 2. 上个月 / 上月
    if (text.includes('上个月') || text.includes('上月') || text.includes('上个自然月')) {
      return {
        key: 'last_month',
        label: '上个月',
        sqlFilter:
          "o.created_at >= date_trunc('month', NOW() - INTERVAL '1 month') AND o.created_at < date_trunc('month', NOW())",
      };
    }

    // 3. 近 7 天 / 最近一周 / 本周
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

    // 4. 今天 / 当日
    if (text.includes('今天') || text.includes('当日') || text.includes('今日')) {
      return {
        key: 'today',
        label: '今日',
        sqlFilter: "o.created_at >= date_trunc('day', NOW())",
      };
    }

    // 5. 今年 / 本年度
    if (text.includes('今年') || text.includes('本年度') || text.includes('年内')) {
      return {
        key: 'this_year',
        label: '今年',
        sqlFilter: "o.created_at >= date_trunc('year', NOW())",
      };
    }

    return undefined;
  }
}
