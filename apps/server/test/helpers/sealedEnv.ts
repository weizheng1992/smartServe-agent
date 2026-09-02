/**
 * 🧪 密封测试环境 (Sealed Test Environment) — Phase 0 安全网基建
 *
 * 以 testcontainers 拉起一次性 PostgreSQL + Redis,通过仓库自带的
 * `bun run db:push`(drizzle-kit push)应用 packages/db 完整 schema,
 * 使测试完全不依赖本机 docker:up 常驻服务与存量数据。
 *
 * 用法(必须在 beforeAll 中,且在任何 db/engine/tools 导入之前):
 *   const sealed = await initSealedEnv();
 *   const { db, getDrizzle } = await loadDb(); // 动态导入,保证 env 已注入
 *
 * ⚠️ bun test 同进程共享模块缓存:凡直接或间接使用 db/tools 的测试文件
 * 都必须走本文件的动态导入模式;静态导入会在 env 注入前把全局连接池
 * 锁死到默认地址。resetPooledClients() 会对已污染的全局池做兜底清理。
 */
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { PostgreSqlContainer } from '@testcontainers/postgresql';
import { RedisContainer } from '@testcontainers/redis';
import { Pool } from 'pg';

const REPO_ROOT = resolve(import.meta.dir, '../../../..');

/** 与 docker-compose.yml 的 postgres 服务保持一致 */
const PG_IMAGE = 'postgres:15-alpine';

export interface SeededTenant {
  businessId: string;
  name: string;
  planTier?: string;
  status?: string;
}

export interface SealedEnv {
  databaseUrl: string;
  redisUrl: string;
  pg: Pool;
  /** 清空全部业务表(保留 schema),测试间隔离用 */
  resetDb: () => Promise<void>;
  /** 写入最小租户 fixture(默认 ecommerce/nike/adidas),幂等 */
  seedTenants: (tenants?: SeededTenant[]) => Promise<void>;
}

let bootstrap: Promise<SealedEnv> | null = null;

/** 清掉 db/tools 包挂在 globalThis 上的全局连接池/客户端,防止进程内先于本模块初始化 */
function resetPooledClients(): void {
  const g = globalThis as unknown as Record<string, unknown>;
  try {
    const oldRedis = g.__redisClient as { disconnect?: () => void } | null;
    if (oldRedis && typeof oldRedis.disconnect === 'function') {
      oldRedis.disconnect();
    }
  } catch {
    // best-effort:旧客户端清理失败不影响新容器接管
  }
  g.__redisClient = null;
  g.__useRedis = false;
  g.__pgPool = null;
  g.__drizzleDb = null;
}

/** 用仓库自己的 db:push 流程把 schema 应用到容器数据库 */
function pushSchema(databaseUrl: string): void {
  const res = spawnSync(process.execPath, ['run', 'db:push'], {
    cwd: REPO_ROOT,
    env: { ...process.env, DATABASE_URL: databaseUrl },
    stdin: 'ignore',
    encoding: 'utf8',
    timeout: 120_000,
  });
  if (res.status !== 0) {
    throw new Error(`[sealedEnv] drizzle-kit push 失败 (exit ${res.status}):\n${res.stdout}\n${res.stderr}`);
  }
}

export function initSealedEnv(): Promise<SealedEnv> {
  bootstrap ??= (async () => {
    resetPooledClients();

    const pgContainer = await new PostgreSqlContainer(PG_IMAGE).start();
    const redisContainer = await new RedisContainer().start();

    const databaseUrl = pgContainer.getConnectionUri();
    const redisUrl = redisContainer.getConnectionUrl();

    // 必须在动态 import db/tools/engine 之前注入 env
    process.env.DATABASE_URL = databaseUrl;
    process.env.REDIS_URL = redisUrl;

    pushSchema(databaseUrl);

    const pg = new Pool({ connectionString: databaseUrl, max: 5 });

    const resetDb = async (): Promise<void> => {
      const { rows } = await pg.query(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename NOT LIKE 'drizzle%'",
      );
      if (rows.length === 0) return;
      const list = rows.map((r) => `"${(r as { tablename: string }).tablename}"`).join(', ');
      await pg.query(`TRUNCATE TABLE ${list} RESTART IDENTITY CASCADE`);
    };

    const DEFAULT_TENANTS: SeededTenant[] = [
      { businessId: 'ecommerce', name: '默认电商租户' },
      { businessId: 'nike', name: 'Nike 官方旗舰店' },
      { businessId: 'adidas', name: 'Adidas 官方旗舰店' },
    ];

    const seedTenants = async (tenants: SeededTenant[] = DEFAULT_TENANTS): Promise<void> => {
      for (const t of tenants) {
        await pg.query(
          `INSERT INTO tenants (business_id, name, plan_tier, status)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (business_id) DO NOTHING`,
          [t.businessId, t.name, t.planTier ?? 'free', t.status ?? 'active'],
        );
      }
    };

    return { databaseUrl, redisUrl, pg, resetDb, seedTenants };
  })();
  return bootstrap;
}

/** 在密封 env 就绪后动态导入 db 包,保证连接池指向容器 */
export async function loadDb(): Promise<typeof import('db')> {
  await initSealedEnv();
  return import('db');
}

/** 在密封 env 就绪后动态导入 engine 包 */
export async function loadEngine(): Promise<typeof import('engine')> {
  await initSealedEnv();
  return import('engine');
}

export function getRepoRoot(): string {
  return REPO_ROOT;
}
