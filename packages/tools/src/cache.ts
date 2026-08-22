import Redis from "ioredis";

const globalForRedis = globalThis as unknown as {
  __redisClient?: Redis | null;
  __useRedis?: boolean;
};

// Safe Redis initialization with automatic silent fallback to local Map
export let redis: Redis | null = globalForRedis.__redisClient || null;
export let useRedis = globalForRedis.__useRedis ?? false;

if (!redis) {
  try {
    const redisUrl =
      process.env.REDIS_URL || "redis://:redis_password@127.0.0.1:6379";
    console.log(
      `[Cache Redis] 正在尝试物理连接至 Redis Server: ${redisUrl}...`,
    );

    redis = new Redis(redisUrl, {
      connectTimeout: 1500, // 1.5秒快速超时
      maxRetriesPerRequest: null,
      retryStrategy(times) {
        return Math.min(times * 500, 5000);
      },
      showFriendlyErrorStack: false,
    });

    if (process.env.NODE_ENV !== "production") {
      globalForRedis.__redisClient = redis;
    }

    redis.on("ready", () => {
      console.log(
        "[Cache Redis] ✅ Redis 缓存物理连接并鉴权成功！启用分布式 TTL 缓存。",
      );
      useRedis = true;
      if (process.env.NODE_ENV !== "production") {
        globalForRedis.__useRedis = true;
      }
    });

    redis.on("error", () => {
      if (useRedis) {
        console.warn(
          "[Cache Redis] ⚠️ Redis 连接异常，系统已自动无缝切换至: Local Map Cache 本地内存缓存模式！",
        );
        useRedis = false;
        if (process.env.NODE_ENV !== "production") {
          globalForRedis.__useRedis = false;
        }
      }
    });
  } catch (e) {
    console.warn(
      "[Cache Redis] ⚠️ Redis 初始化失败，默认降级至 Local Map 本地缓存:",
      e,
    );
  }
}

// In-Memory fallback cache with TTL
const localMemoryCache = new Map<
  string,
  { data: unknown; timestamp: number; ttlMs: number }
>();

export const toolCache = {
  async get<T>(key: string): Promise<T | null> {
    const isProd = process.env.NODE_ENV === "production";
    const cacheDisabled = process.env.DISABLE_TOOL_CACHE === "true";
    const shouldReadCache = isProd && !cacheDisabled;
    if (!shouldReadCache) return null;

    if (useRedis && redis) {
      try {
        const cachedStr = await redis.get(key);
        if (cachedStr) {
          return JSON.parse(cachedStr) as T;
        }
      } catch (redisErr) {
        console.warn(
          "[Tool Cache Warning] Redis 读取失败，自动降级至内存缓存:",
          redisErr,
        );
      }
    }

    const item = localMemoryCache.get(key);
    if (item) {
      if (Date.now() - item.timestamp < item.ttlMs) {
        return item.data as T;
      }
      localMemoryCache.delete(key);
    }

    return null;
  },

  async set<T>(key: string, value: T, ttlSeconds = 60): Promise<void> {
    localMemoryCache.set(key, {
      data: value,
      timestamp: Date.now(),
      ttlMs: ttlSeconds * 1000,
    });

    if (useRedis && redis) {
      try {
        await redis.set(key, JSON.stringify(value), "EX", ttlSeconds);
        console.log(
          `[Tool Cache Set] ✅ 数据已存入 Redis，TTL = ${ttlSeconds}s`,
        );
      } catch (redisErr) {
        console.warn("[Tool Cache Warning] Redis 写入失败:", redisErr);
      }
    }
  },

  async delete(key: string): Promise<void> {
    localMemoryCache.delete(key);

    if (useRedis && redis) {
      try {
        await redis.del(key);
        console.log("[Tool Cache Invalidate] 🧹 Redis 缓存已物理清除。");
      } catch (redisErr) {
        console.warn("[Tool Cache Warning] Redis 清除失败:", redisErr);
      }
    }
  },
};
