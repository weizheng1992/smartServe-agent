import { redis, useRedis } from 'tools';

// 内存滑动窗口降级存储（当 Redis 离线时使用）
const localRequestCounts = new Map<string, { count: number; resetAt: number }>();
const localTokenUsages = new Map<string, { total: number; dateStr: string }>();

const MAX_REQUESTS_PER_MINUTE = 60; // 每分钟最多 60 次 API 请求
const MAX_DAILY_TOKENS = 500000; // 每用户/租户每日最多 500,000 Tokens

export interface QuotaCheckResult {
  allowed: boolean;
  reason?: string;
  remainingRequests?: number;
  remainingTokens?: number;
}

export async function checkTenantQuotaGuard(userId: string, businessId = 'ecommerce'): Promise<QuotaCheckResult> {
  const now = Date.now();
  const dateStr = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
  const minuteKey = `rate:${businessId}:${userId}:${Math.floor(now / 60000)}`;
  const dailyTokenKey = `quota:${businessId}:${userId}:${dateStr}`;

  // 1. 优先使用 Redis 分布式滑动窗口
  if (useRedis && redis) {
    try {
      // 检查请求频率
      const currentReqs = await redis.incr(minuteKey);
      if (currentReqs === 1) {
        await redis.expire(minuteKey, 60);
      }
      if (currentReqs > MAX_REQUESTS_PER_MINUTE) {
        return {
          allowed: false,
          reason: `触发租户请求防暴刷限流：单用户 1 分钟内最多支持 ${MAX_REQUESTS_PER_MINUTE} 次请求，请稍后再试。`,
          remainingRequests: 0,
        };
      }

      // 检查每日 Token 配额
      const currentTokensStr = await redis.get(dailyTokenKey);
      const currentTokens = currentTokensStr ? Number.parseInt(currentTokensStr, 10) : 0;
      if (currentTokens >= MAX_DAILY_TOKENS) {
        return {
          allowed: false,
          reason: `触发租户算力保护：您的账户今日 Token 算力消耗已达上限 (${MAX_DAILY_TOKENS} Tokens)，请明日或联系管理员提升配额。`,
          remainingTokens: 0,
        };
      }

      return {
        allowed: true,
        remainingRequests: MAX_REQUESTS_PER_MINUTE - currentReqs,
        remainingTokens: MAX_DAILY_TOKENS - currentTokens,
      };
    } catch (err) {
      console.warn('[QuotaGuard] Redis check failed, falling back to memory:', err);
    }
  }

  // 2. Redis 离线或异常时的内存降级检查
  let reqEntry = localRequestCounts.get(minuteKey);
  if (!reqEntry || now > reqEntry.resetAt) {
    reqEntry = { count: 1, resetAt: now + 60000 };
    localRequestCounts.set(minuteKey, reqEntry);
  } else {
    reqEntry.count++;
  }

  if (reqEntry.count > MAX_REQUESTS_PER_MINUTE) {
    return {
      allowed: false,
      reason: `触发租户请求防暴刷限流 (内存降级)：单用户 1 分钟内最多支持 ${MAX_REQUESTS_PER_MINUTE} 次请求，请稍后再试。`,
      remainingRequests: 0,
    };
  }

  let tokenEntry = localTokenUsages.get(dailyTokenKey);
  if (!tokenEntry || tokenEntry.dateStr !== dateStr) {
    tokenEntry = { total: 0, dateStr };
    localTokenUsages.set(dailyTokenKey, tokenEntry);
  }

  if (tokenEntry.total >= MAX_DAILY_TOKENS) {
    return {
      allowed: false,
      reason: `触发租户算力保护 (内存降级)：您的账户今日 Token 算力消耗已达上限 (${MAX_DAILY_TOKENS} Tokens)。`,
      remainingTokens: 0,
    };
  }

  return {
    allowed: true,
    remainingRequests: MAX_REQUESTS_PER_MINUTE - reqEntry.count,
    remainingTokens: MAX_DAILY_TOKENS - tokenEntry.total,
  };
}

export async function recordTokenUsage(userId: string, tokensUsed: number, businessId = 'ecommerce'): Promise<void> {
  if (tokensUsed <= 0) return;
  const dateStr = new Date().toISOString().split('T')[0];
  const dailyTokenKey = `quota:${businessId}:${userId}:${dateStr}`;

  if (useRedis && redis) {
    try {
      await redis.incrby(dailyTokenKey, tokensUsed);
      await redis.expire(dailyTokenKey, 86400 * 2); // 保留 2 天
      return;
    } catch (err) {
      console.warn('[QuotaGuard] Redis incrby failed:', err);
    }
  }

  const entry = localTokenUsages.get(dailyTokenKey) || { total: 0, dateStr };
  entry.total += tokensUsed;
  localTokenUsages.set(dailyTokenKey, entry);
}
