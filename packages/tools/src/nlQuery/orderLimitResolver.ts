import type { OrderLimitResult } from './types';

/**
 * 🌟 排序方向与 TopN 解析器 (Order & Limit Resolver)
 * 职责：解析用户显式指定的排序要求（覆盖指标默认值）及限制条数（Top N）
 */
export class OrderLimitResolver {
  public static resolve(input: string): OrderLimitResult {
    let directionOverride: 'ASC' | 'DESC' | undefined;
    let limit = 5;

    const text = input.toLowerCase();

    // 1. 判定排序方向显式改写
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

    // 2. 提取 TopN / 倒数第 N
    const limitPatterns = [/(?:top|前|排名前|倒数第?|最后)\s*(\d+)/i, /(\d+)\s*(?:个|名|款|件|条)/i];

    for (const pattern of limitPatterns) {
      const match = text.match(pattern);
      if (match && match[1]) {
        const parsed = Number.parseInt(match[1], 10);
        if (!Number.isNaN(parsed) && parsed > 0) {
          limit = Math.min(parsed, 50); // 上限保护 50 条
          break;
        }
      }
    }

    return {
      directionOverride,
      limit,
    };
  }
}
