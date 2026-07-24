import { type Order, db } from 'db';
import Redis from 'ioredis';
import { z } from 'zod';
import { registerTool } from './registry';

// 1-minute TTL Cache for getOrderStatus
const orderStatusCache = new Map<string, { data: Order; timestamp: number }>();
const CACHE_TTL_MS = 60000; // 1 minute

// Safe Redis initialization with automatic silent fallback to local Map
export let redis: Redis | null = null;
export let useRedis = false;

try {
  const redisUrl = process.env.REDIS_URL || 'redis://:redis_password@127.0.0.1:6379';
  console.log(`[Cache Redis] 正在尝试物理连接至 Redis Server: ${redisUrl}...`);

  redis = new Redis(redisUrl, {
    connectTimeout: 1500, // 1.5秒快速超时
    maxRetriesPerRequest: null,
    retryStrategy(times) {
      // 每次重连间隔逐渐增加，最大间隔 5 秒，避免高频重连打满日志与 CPU
      return Math.min(times * 500, 5000);
    },
    showFriendlyErrorStack: false,
  });

  redis.on('ready', () => {
    console.log('[Cache Redis] ✅ Redis 缓存物理连接并鉴权成功！启用分布式 TTL 缓存。');
    useRedis = true;
  });

  redis.on('error', (err) => {
    // 捕获连接失败等物理异常，静默降级，绝不抛出 Unhandled Exception 导致服务挂掉
    if (useRedis) {
      console.warn('[Cache Redis] ⚠️ Redis 连接异常，系统已自动无缝切换至: Local Map Cache 本地内存缓存模式！');
      useRedis = false;
    }
  });
} catch (e) {
  console.warn('[Cache Redis] ⚠️ Redis 初始化失败，默认降级至 Local Map 本地缓存:', e);
}

export const getOrderStatus = {
  name: 'getOrderStatus',
  description: 'Get the status of a specific order by order ID.',
  schema: z.object({
    orderId: z.string().describe('The unique order identifier.'),
  }),
  execute: async ({ orderId }: { orderId: string }) => {
    const cacheKey = `cache:order_status:${orderId}`;

    // 1. 优先尝试使用 Redis 物理分布式缓存
    if (useRedis && redis) {
      try {
        const cachedStr = await redis.get(cacheKey);
        if (cachedStr) {
          console.log(`[Tool Cache Hit] 🎯 物理 Redis 命中！直接返回 Order ${orderId} 缓存数据！`);
          return JSON.parse(cachedStr);
        }
      } catch (redisErr) {
        console.warn('[Tool Cache Warning] Redis 读取失败，自动降级至内存缓存:', redisErr);
      }
    }

    // 2. 备用 Local Map 本地缓存
    const now = Date.now();
    const cached = orderStatusCache.get(orderId);
    if (cached && now - cached.timestamp < CACHE_TTL_MS) {
      console.log(`[Tool Cache Hit] 🎯 内存 Local Map 命中！直接返回 Order ${orderId} 物流数据！`);
      return cached.data;
    }

    // 3. 缓存均未命中，物理查询
    const order = await db.getOrder(orderId);
    if (order) {
      // 写入 Local Map 缓存
      orderStatusCache.set(orderId, { data: order, timestamp: now });

      // 写入 Redis 缓存（TTL 设置为 60 秒）
      if (useRedis && redis) {
        try {
          await redis.set(cacheKey, JSON.stringify(order), 'EX', 60);
          console.log('[Tool Cache Set] ✅ 物流数据已存入 Redis，TTL = 60s');
        } catch (redisErr) {
          console.warn('[Tool Cache Warning] Redis 写入失败:', redisErr);
        }
      }
      return order;
    }

    return {
      error: `Order ${orderId} not found in the physical database. Please run seed or push to create records.`,
    };
  },
};

export const processRefund = {
  name: 'processRefund',
  description: 'Process a refund for an order.',
  schema: z.object({
    orderId: z.string().describe('The unique order identifier.'),
    reason: z.string().describe('The reason for processing the refund.'),
  }),
  execute: async ({ orderId, reason, threadId }: { orderId: string; reason: string; threadId?: string }) => {
    // SaaS 多租户隔离：根据 threadId 物理 SQL 溯源所属商户租户，采用 db.execute 彻底规避对 drizzle-orm 的依赖警告
    let businessId = 'ecommerce';
    if (threadId) {
      try {
        const { db: physicalDb } = require('db');
        const res = await physicalDb.execute(
          `SELECT "business_id" AS "businessId" FROM threads WHERE id = '${threadId}'`,
        );
        if (res.rows && res.rows[0]) {
          const row = res.rows[0] as any;
          businessId = row.businessId || row.business_id || 'ecommerce';
        }
      } catch (err) {
        console.warn('[Refund Tool Policy] Failed to fetch thread tenant ID via physical execute:', err);
      }
    }

    // 物理提取当前商户 SOP 退货时效规定（Nike 30天，Adidas 14天，电商主站 7天）
    let returnWindowDays = 7;
    if (businessId === 'nike') {
      returnWindowDays = 30;
    } else if (businessId === 'adidas') {
      returnWindowDays = 14;
    }

    const order = await db.getOrder(orderId);
    if (order) {
      // 物理时效比对：核验该笔订单距送达/预计送达日期是否已超期（SOP Policy Guardrail）
      const deliveryDate = new Date(order.estimatedDelivery);
      const currentDate = new Date();
      const diffTime = Math.abs(currentDate.getTime() - deliveryDate.getTime());
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

      if (diffDays > returnWindowDays) {
        console.log(
          `[Refund Tool Guardrail] ❌ 政策拦截：商户 [${businessId}] 退货期为 ${returnWindowDays} 天，订单已过去 ${diffDays} 天！`,
        );
        return {
          error: `⚠️ 退款政策拦截：根据商户 [${businessId.toUpperCase()}] 官方售后 SOP 规范，退货时效为订单送达之日起 ${returnWindowDays} 天内。该订单送达日期为 ${order.estimatedDelivery}，当前已逾期 ${diffDays} 天，超出合规退款时效。物理拒绝执行退款！`,
          orderId,
          status: 'rejected_by_policy',
          businessId,
          returnWindowDays,
          elapsedDays: diffDays,
        };
      }

      // Update the status of the order to "refunded" in the orders database table!
      await db.execute(`UPDATE "orders" SET status = 'refunded' WHERE "orderId" = '${orderId}'`);

      // Invalidate the caches for this order to ensure consistency!
      const cacheKey = `cache:order_status:${orderId}`;

      // 1. 清除 Local Map 缓存
      orderStatusCache.delete(orderId);

      // 2. 清除 Redis 缓存
      if (useRedis && redis) {
        try {
          await redis.del(cacheKey);
          console.log('[Tool Cache Invalidate] 🧹 Redis 缓存已物理清除。');
        } catch (redisErr) {
          console.warn('[Tool Cache Warning] Redis 清除失败:', redisErr);
        }
      }

      console.log(
        `[Tool Cache Invalidate] 🧹 因退款发起，已全渠道物理清除 Order ${orderId} 的物流缓存，确保缓存强一致性！`,
      );

      return {
        orderId,
        status: 'refunded',
        refundAmount: '$99.99',
        reason,
        transactionId: `TXN_${Math.random().toString(36).substr(2, 9).toUpperCase()}`,
        message: 'Physical refund process initiated in Postgres database.',
      };
    }
    return {
      error: `Failed to process refund: Order ${orderId} does not exist in physical Postgres database.`,
    };
  },
};

registerTool(getOrderStatus);
registerTool(processRefund);
