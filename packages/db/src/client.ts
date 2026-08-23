import { type NodePgDatabase, drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";
import type { Message, Order } from "./schema";
import * as schema from "./schema";

export interface DBExecutorResult {
  rows: unknown[];
}

export interface CompiledSQL {
  text: string;
  values: unknown[];
}

export interface DBThread {
  id: string;
  userId: string;
  businessId: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface DBInterface {
  select: () => DBInterface;
  insert: () => DBInterface;
  update: () => DBInterface;
  delete: () => DBInterface;
  values: () => DBInterface;
  getMessages: (threadId: string) => Promise<Message[]>;
  addMessage: (message: Message) => Promise<void>;
  getOrder: (orderId: string) => Promise<Order | null>;
  execute: (queryStr: string, params?: unknown[]) => Promise<DBExecutorResult>;
  executeReadOnlyAnalyticsQuery: <T = Record<string, unknown>>(
    compiled: CompiledSQL | { text: string; values: unknown[] },
  ) => Promise<T[]>;
  findOrCreateUserByEmail: (
    email: string,
  ) => Promise<{ id: string; email: string }>;
  getUserThreads: (userId: string) => Promise<DBThread[]>;
  getThread: (threadId: string) => Promise<DBThread | null>;
  createThread: (
    threadId: string,
    userId: string,
    businessId?: string,
  ) => Promise<DBThread>;
  deleteThread: (threadId: string) => Promise<boolean>;
}

const globalForDb = globalThis as unknown as {
  __pgPool?: Pool | null;
  __drizzleDb?: NodePgDatabase<typeof schema> | null;
};

let pgPool: Pool | null = globalForDb.__pgPool || null;
let drizzleDb: NodePgDatabase<typeof schema> | null =
  globalForDb.__drizzleDb || null;

export function getPgPool(): Pool {
  if (pgPool) return pgPool;

  const dbUrl =
    process.env.DATABASE_URL ||
    "postgres://agent_user:agent_password@localhost:5432/agent_platform";

  try {
    console.log(
      `[DB] 正在物理连接至 PostgreSQL 数据库: ${dbUrl.replace(/:([^:@]+)@/, ":****@")}...`,
    );
    pgPool = new Pool({
      connectionString: dbUrl,
      connectionTimeoutMillis: 5000,
      max: 20,
      idleTimeoutMillis: 30000,
    });
    if (process.env.NODE_ENV !== "production") {
      globalForDb.__pgPool = pgPool;
    }
    return pgPool;
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    throw new Error(
      `❌ [DATABASE ERROR] Failed to initialize PostgreSQL pool: ${errMsg}`,
    );
  }
}

export function getDrizzle(): NodePgDatabase<typeof schema> {
  if (drizzleDb) return drizzleDb;
  const pool = getPgPool();
  drizzleDb = drizzle(pool, { schema });
  if (process.env.NODE_ENV !== "production") {
    globalForDb.__drizzleDb = drizzleDb;
  }
  return drizzleDb;
}

/**
 * 🛡️ 执行只读分析型 SQL 查询沙箱 (Read-Only Analytics Sandbox)
 * 1. 强制只读事务: SET TRANSACTION READ ONLY
 * 2. 3000ms 硬超时防死锁与慢查询: SET LOCAL statement_timeout = '3000ms'
 * 3. 预编译参数防注入绑定: client.query(compiled.text, compiled.values)
 */
export async function executeReadOnlyAnalyticsQuery<
  T = Record<string, unknown>,
>(compiled: CompiledSQL | { text: string; values: unknown[] }): Promise<T[]> {
  const pool = getPgPool();
  const client = await pool.connect();
  try {
    await client.query("BEGIN TRANSACTION READ ONLY");
    await client.query("SET LOCAL statement_timeout = '3000ms'");
    const res = await client.query(compiled.text, compiled.values);
    await client.query("COMMIT");
    return (res.rows || []) as T[];
  } catch (err) {
    try {
      await client.query("ROLLBACK");
    } catch (_) {
      // ignore rollback errors
    }
    throw err;
  } finally {
    client.release();
  }
}

/**
 * 确保 userId 转换为真实的 PostgreSQL users 表 UUID
 */
async function resolveAndEnsurePgUserId(
  pool: Pool,
  userId: string,
): Promise<string> {
  const isUuid =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      userId,
    );
  if (isUuid) {
    const checkUser = await pool.query(
      "SELECT id FROM users WHERE id = $1 LIMIT 1",
      [userId],
    );
    if (checkUser.rows && checkUser.rows.length > 0) {
      return userId;
    }
    const email = `user_${userId.substring(0, 8)}@example.com`;
    await pool.query(
      "INSERT INTO users (id, email, created_at) VALUES ($1, $2, NOW()) ON CONFLICT (id) DO NOTHING",
      [userId, email],
    );
    return userId;
  }

  const fallbackEmail =
    userId === "u_default_id" || userId.startsWith("u_")
      ? "test@example.com"
      : `${userId}@example.com`;

  const selectUser = await pool.query(
    "SELECT id FROM users WHERE LOWER(email) = LOWER($1) LIMIT 1",
    [fallbackEmail],
  );
  if (selectUser.rows && selectUser.rows.length > 0) {
    return selectUser.rows[0].id as string;
  }

  const newUuid = crypto.randomUUID
    ? crypto.randomUUID()
    : require("node:crypto").randomUUID();
  await pool.query(
    "INSERT INTO users (id, email, created_at) VALUES ($1, $2, NOW()) ON CONFLICT (id) DO NOTHING",
    [newUuid, fallbackEmail],
  );
  return newUuid;
}

export const db: DBInterface = {
  select: (): DBInterface => db,
  insert: (): DBInterface => db,
  update: (): DBInterface => db,
  delete: (): DBInterface => db,
  values: (): DBInterface => db,

  findOrCreateUserByEmail: async (
    email: string,
  ): Promise<{ id: string; email: string }> => {
    const pool = getPgPool();
    const selectRes = await pool.query(
      "SELECT id, email FROM users WHERE LOWER(email) = LOWER($1) LIMIT 1",
      [email],
    );
    if (selectRes.rows && selectRes.rows.length > 0) {
      const row = selectRes.rows[0] as { id: string; email: string };
      return { id: row.id, email: row.email };
    }

    const id = crypto.randomUUID
      ? crypto.randomUUID()
      : require("node:crypto").randomUUID();
    await pool.query(
      "INSERT INTO users (id, email, created_at) VALUES ($1, $2, NOW()) ON CONFLICT (id) DO NOTHING",
      [id, email],
    );
    return { id, email };
  },

  getUserThreads: async (userId: string): Promise<DBThread[]> => {
    const pool = getPgPool();
    const pgUserId = await resolveAndEnsurePgUserId(pool, userId);

    const res = await pool.query(
      'SELECT id, "user_id" AS "userId", "business_id" AS "businessId", status, "created_at" AS "createdAt", "updated_at" AS "updatedAt" FROM threads WHERE "user_id" = $1 ORDER BY "updated_at" DESC',
      [pgUserId],
    );
    return res.rows.map((row: any) => ({
      id: (row.id || "") as string,
      userId: (row.userId || row.user_id || "") as string,
      businessId: (row.businessId || row.business_id || "ecommerce") as string,
      status: (row.status || "active") as string,
      createdAt: (row.createdAt ||
        row.created_at ||
        new Date().toISOString()) as string,
      updatedAt: (row.updatedAt ||
        row.updated_at ||
        new Date().toISOString()) as string,
    })) as DBThread[];
  },

  getThread: async (threadId: string): Promise<DBThread | null> => {
    const pool = getPgPool();
    const res = await pool.query(
      'SELECT id, "user_id" AS "userId", "business_id" AS "businessId", status, "created_at" AS "createdAt", "updated_at" AS "updatedAt" FROM threads WHERE id = $1 LIMIT 1',
      [threadId],
    );
    if (res.rows && res.rows.length > 0) {
      const row = res.rows[0] as any;
      return {
        id: (row.id || "") as string,
        userId: (row.userId || row.user_id || "") as string,
        businessId: (row.businessId ||
          row.business_id ||
          "ecommerce") as string,
        status: (row.status || "active") as string,
        createdAt: (row.createdAt ||
          row.created_at ||
          new Date().toISOString()) as string,
        updatedAt: (row.updatedAt ||
          row.updated_at ||
          new Date().toISOString()) as string,
      };
    }
    return null;
  },

  createThread: async (
    threadId: string,
    userId: string,
    businessId?: string,
  ): Promise<DBThread> => {
    const pool = getPgPool();
    const pgUserId = await resolveAndEnsurePgUserId(pool, userId);

    const existing = await pool.query(
      'SELECT id, "user_id" AS "userId", "business_id" AS "businessId", status, "created_at" AS "createdAt", "updated_at" AS "updatedAt" FROM threads WHERE id = $1 LIMIT 1',
      [threadId],
    );

    if (existing.rows && existing.rows.length > 0) {
      const row = existing.rows[0] as any;
      const existingBizId = (row.businessId ||
        row.business_id ||
        "ecommerce") as string;
      // 🛡️ 多租户身份不被默认 fallback 降级覆盖：如果已有会话属于特定商户（如 adidas/nike），默认传入的 ecommerce 或 undefined 不能冲掉商户身份
      let finalBusinessId = existingBizId;
      if (businessId && businessId !== "ecommerce") {
        finalBusinessId = businessId;
      } else if (!existingBizId || existingBizId === "ecommerce") {
        finalBusinessId = businessId || "ecommerce";
      }
      await pool.query(
        'UPDATE threads SET "updated_at" = NOW(), "business_id" = $2 WHERE id = $1',
        [threadId, finalBusinessId],
      );
      return {
        id: threadId,
        userId: (row.userId || row.user_id || pgUserId) as string,
        businessId: finalBusinessId,
        status: (row.status || "active") as string,
        createdAt: (row.createdAt ||
          row.created_at ||
          new Date().toISOString()) as string,
        updatedAt: new Date().toISOString(),
      };
    }

    const activeBusinessId = businessId || "ecommerce";
    await pool.query(
      'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") VALUES ($1, $2, $3, $4, NOW(), NOW()) ON CONFLICT (id) DO UPDATE SET updated_at = NOW()',
      [threadId, pgUserId, activeBusinessId, "active"],
    );
    return {
      id: threadId,
      userId: pgUserId,
      businessId: activeBusinessId,
      status: "active",
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
  },

  getMessages: async (threadId: string): Promise<Message[]> => {
    const pool = getPgPool();
    const res = await pool.query(
      `SELECT id, "thread_id" AS "threadId", role, content, timestamp
       FROM messages
       WHERE "thread_id" = $1
       ORDER BY
         timestamp ASC,
         CASE role
           WHEN 'system' THEN 1
           WHEN 'user' THEN 2
           WHEN 'assistant' THEN 3
           ELSE 4
         END ASC,
         id ASC`,
      [threadId],
    );
    const rows = res.rows as Array<{
      id: string;
      thread_id?: string;
      threadId?: string;
      role: string;
      content: string;
      timestamp: string;
    }>;
    return rows.map((r) => ({
      id: r.id,
      threadId: r.thread_id || r.threadId || "",
      role: r.role as any,
      content: r.content,
      timestamp: r.timestamp,
    }));
  },

  addMessage: async (message: Message): Promise<void> => {
    const pool = getPgPool();
    await pool.query(
      `INSERT INTO messages (id, "thread_id", role, content, timestamp) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (id) DO NOTHING`,
      [
        message.id,
        message.threadId,
        message.role,
        message.content,
        message.timestamp,
      ],
    );
    await pool.query(`UPDATE threads SET updated_at = NOW() WHERE id = $1`, [
      message.threadId,
    ]);
  },

  getOrder: async (orderId: string): Promise<Order | null> => {
    const pool = getPgPool();
    const res = await pool.query(
      'SELECT order_id AS "orderId", status, carrier, tracking_number AS "trackingNumber", estimated_delivery AS "estimatedDelivery" FROM orders WHERE order_id = $1',
      [orderId],
    );
    const rows = res.rows as Array<{
      order_id?: string;
      orderId?: string;
      status: string;
      carrier: string;
      tracking_number?: string;
      trackingNumber?: string;
      estimated_delivery?: string;
      estimatedDelivery?: string;
    }>;
    if (rows && rows.length > 0) {
      const row = rows[0];
      return {
        orderId: row.order_id || row.orderId || "",
        status: row.status,
        carrier: row.carrier,
        trackingNumber: row.tracking_number || row.trackingNumber || "",
        estimatedDelivery:
          row.estimated_delivery || row.estimatedDelivery || "",
      } as Order;
    }
    return null;
  },

  execute: async (
    queryStr: string,
    params?: unknown[],
  ): Promise<DBExecutorResult> => {
    const pool = getPgPool();
    const res = await pool.query(queryStr, params);
    return { rows: res.rows as unknown[] };
  },

  executeReadOnlyAnalyticsQuery: async <T = Record<string, unknown>>(
    compiled: CompiledSQL | { text: string; values: unknown[] },
  ): Promise<T[]> => {
    return executeReadOnlyAnalyticsQuery<T>(compiled);
  },

  deleteThread: async (threadId: string): Promise<boolean> => {
    const pool = getPgPool();
    try {
      await pool.query("BEGIN");
      await pool.query("DELETE FROM messages WHERE thread_id = $1", [threadId]);
      await pool.query("DELETE FROM pending_approvals WHERE thread_id = $1", [
        threadId,
      ]);
      await pool.query("DELETE FROM session_metrics WHERE thread_id = $1", [
        threadId,
      ]);
      await pool.query("DELETE FROM task_memory WHERE thread_id = $1", [
        threadId,
      ]);
      await pool.query("DELETE FROM episodic_events WHERE thread_id = $1", [
        threadId,
      ]);
      await pool.query("DELETE FROM agent_jobs WHERE thread_id = $1", [
        threadId,
      ]);
      await pool.query("DELETE FROM intent_logs WHERE thread_id = $1", [
        threadId,
      ]);
      await pool.query("DELETE FROM low_confidence_logs WHERE thread_id = $1", [
        threadId,
      ]);

      const res = await pool.query("DELETE FROM threads WHERE id = $1", [
        threadId,
      ]);
      await pool.query("COMMIT");
      return (res.rowCount ?? 0) > 0;
    } catch (e) {
      await pool.query("ROLLBACK");
      console.error(`[DB] Error deleting thread ${threadId}:`, e);
      return false;
    }
  },
};
