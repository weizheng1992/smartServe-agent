import { type NodePgDatabase, drizzle } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import type { Message, Order } from './schema';
import * as schema from './schema';

export interface DBQueryResult<T> {
  rows: T[];
}

export interface FakeQueryObject {
  text?: string;
  values?: unknown[];
}

export interface MemoryDatabaseState {
  users: Map<string, { id: string; email: string; createdAt: string }>;
  threads: Map<
    string,
    { id: string; userId: string; businessId: string; status: string; createdAt: string; updatedAt: string }
  >;
  orders: Map<
    string,
    {
      order_id: string;
      status: string;
      carrier: string;
      tracking_number: string;
      estimated_delivery: string;
      user_id: string;
      business_id: string;
      total_amount: number;
    }
  >;
  products: Map<
    string,
    {
      id: string;
      business_id: string;
      name: string;
      description: string;
      price: number;
      stock: number;
    }
  >;
  orderItems: Array<{
    id: string;
    order_id: string;
    product_id: string;
    quantity: number;
    price_at_purchase: number;
  }>;
  messages: Array<{
    id: string;
    thread_id: string;
    role: string;
    content: string;
    timestamp: string;
  }>;
  pendingApprovals: Array<{
    id: string;
    threadId: string;
    thread_id: string;
    actionType: string;
    action_type: string;
    actionPayload: any;
    action_payload: any;
    status: string;
    deadline: string;
    createdAt: string;
    created_at: string;
  }>;
}

const globalForDb = global as unknown as {
  memoryDb?: MemoryDatabaseState;
};

// 在内存中模拟一个完整的物理数据库表状态
const memoryDb: MemoryDatabaseState = globalForDb.memoryDb ?? {
  users: new Map<string, { id: string; email: string; createdAt: string }>([
    ['u_default_id', { id: 'u_default_id', email: 'test@example.com', createdAt: new Date().toISOString() }],
  ]),
  threads: new Map<
    string,
    { id: string; userId: string; businessId: string; status: string; createdAt: string; updatedAt: string }
  >(),
  orders: new Map([
    [
      'ORD-98712',
      {
        order_id: 'ORD-98712',
        status: 'shipped',
        carrier: 'FedEx',
        tracking_number: '1234567890',
        estimated_delivery: '2026-07-20',
        user_id: 'u_default_id',
        business_id: 'nike',
        total_amount: 139.99,
      },
    ],
    [
      'ORD-55555',
      {
        order_id: 'ORD-55555',
        status: 'completed',
        carrier: 'SF Express',
        tracking_number: 'SF9876543210',
        estimated_delivery: '2026-07-25',
        user_id: 'u_default_id',
        business_id: 'ecommerce',
        total_amount: 49.99,
      },
    ],
  ]),
  products: new Map([
    [
      'prod_nike_1',
      {
        id: 'prod_nike_1',
        business_id: 'nike',
        name: 'Nike Pegasus Trail 5 越野跑鞋',
        description: '专为户外越野打造，搭载高强度 React 缓震泡棉，耐磨抓地橡胶大底。',
        price: 139.99,
        stock: 45,
      },
    ],
    [
      'prod_nike_2',
      {
        id: 'prod_nike_2',
        business_id: 'nike',
        name: 'Nike Element 户外防风连帽衫',
        description: '高透气防泼水面料，反光条设计保障夜间户外运动安全。',
        price: 85.0,
        stock: 30,
      },
    ],
    [
      'prod_adidas_1',
      {
        id: 'prod_adidas_1',
        business_id: 'adidas',
        name: 'Adidas Ultraboost 1.0 经典跑鞋',
        description: '卓越的 Boost 能量回馈中底，Primeknit 贴合针织鞋面。',
        price: 179.99,
        stock: 50,
      },
    ],
    [
      'prod_adidas_2',
      {
        id: 'prod_adidas_2',
        business_id: 'adidas',
        name: 'Adidas Multi-Pack 运动专业棉袜 (3双装)',
        description: '吸湿排汗，足弓加厚减震缓冲。',
        price: 12.5,
        stock: 120,
      },
    ],
    [
      'prod_eco_1',
      {
        id: 'prod_eco_1',
        business_id: 'ecommerce',
        name: '电商主站极绒亲肤抗静电保暖毯',
        description: '高克重复合超细纤维，环保防静电印染，居家车载必备。',
        price: 49.99,
        stock: 85,
      },
    ],
  ]),
  orderItems: [
    {
      id: 'item_nike_1',
      order_id: 'ORD-98712',
      product_id: 'prod_nike_1',
      quantity: 1,
      price_at_purchase: 139.99,
    },
    {
      id: 'item_eco_1',
      order_id: 'ORD-55555',
      product_id: 'prod_eco_1',
      quantity: 1,
      price_at_purchase: 49.99,
    },
  ],
  messages: [],
  pendingApprovals: [],
};

if (process.env.NODE_ENV !== 'production') {
  globalForDb.memoryDb = memoryDb;
}

export class FakePool {
  async connect(): Promise<{
    query: (queryStr: string | FakeQueryObject, params?: unknown[]) => Promise<DBQueryResult<unknown>>;
    release: () => void;
  }> {
    return {
      query: async (queryStr: string | FakeQueryObject, params?: unknown[]): Promise<DBQueryResult<unknown>> => {
        return this.query(queryStr, params);
      },
      release: (): void => {},
    };
  }

  on(event: string, cb: (...args: unknown[]) => void): void {}

  async query(queryStr: string | FakeQueryObject, params?: unknown[]): Promise<DBQueryResult<unknown>> {
    const sqlText = typeof queryStr === 'string' ? queryStr : queryStr.text || '';
    const s = sqlText.trim().replace(/\s+/g, ' ');

    if (s.toUpperCase().includes('CREATE TABLE')) {
      return { rows: [] };
    }

    if (s.toUpperCase().includes('INSERT INTO ORDERS') || s.toUpperCase().includes('INSERT INTO "ORDERS"')) {
      return { rows: [] };
    }

    if (s.toUpperCase().includes('FROM ORDERS') || s.toUpperCase().includes('FROM "ORDERS"')) {
      // Check if querying by user_id
      const userMatch = s.match(/user_id\s*=\s*['"]([^'"]+)['"]/i) || s.match(/user_id\s*=\s*\$1/i);
      if (userMatch) {
        const userId = params && typeof params[0] === 'string' ? params[0] : 'u_default_id';
        const rows = Array.from(memoryDb.orders.values()).filter((o) => o.user_id === userId);
        return { rows } as DBQueryResult<unknown>;
      }

      // Check if querying by raw string user_id
      const rawUserMatch = s.match(/["']user_id["']\s*=\s*['"]([^'"]+)['"]/i);
      if (rawUserMatch) {
        const userId = rawUserMatch[1];
        const rows = Array.from(memoryDb.orders.values()).filter((o) => o.user_id === userId);
        return { rows } as DBQueryResult<unknown>;
      }

      let orderId = params && typeof params[0] === 'string' ? params[0] : '';
      if (!orderId) {
        const orderIdMatch = s.match(/order_id\s*=\s*['"]([^'"]+)['"]/i) || s.match(/orderId\s*=\s*['"]([^'"]+)['"]/i);
        if (orderIdMatch) {
          orderId = orderIdMatch[1];
        }
      }
      const order = orderId ? memoryDb.orders.get(orderId) : null;
      return { rows: order ? [order] : [] } as DBQueryResult<unknown>;
    }

    if (s.toUpperCase().includes('FROM PRODUCTS') || s.toUpperCase().includes('FROM "PRODUCTS"')) {
      const businessId = params && typeof params[0] === 'string' ? params[0] : 'nike';
      const rows = Array.from(memoryDb.products.values()).filter((p) => p.business_id === businessId);
      return { rows } as DBQueryResult<unknown>;
    }

    if (s.toUpperCase().includes('FROM ORDER_ITEMS') || s.toUpperCase().includes('FROM "ORDER_ITEMS"')) {
      let orderId = params && typeof params[0] === 'string' ? params[0] : '';
      if (!orderId) {
        const orderIdMatch = s.match(/order_id\s*=\s*['"]([^'"]+)['"]/i) || s.match(/orderId\s*=\s*['"]([^'"]+)['"]/i);
        if (orderIdMatch) {
          orderId = orderIdMatch[1];
        }
      }
      const rows = orderId ? memoryDb.orderItems.filter((item) => item.order_id === orderId) : [];
      return { rows } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes('INSERT INTO PRODUCTS') ||
      s.toUpperCase().includes('INSERT INTO "PRODUCTS"') ||
      s.toUpperCase().includes('INSERT INTO ORDER_ITEMS') ||
      s.toUpperCase().includes('INSERT INTO "ORDER_ITEMS"')
    ) {
      return { rows: [] };
    }

    if (
      s.toUpperCase().includes('INSERT INTO SESSION_METRICS') ||
      s.toUpperCase().includes('INSERT INTO "SESSION_METRICS"')
    ) {
      return { rows: [] };
    }

    if (s.toUpperCase().includes('FROM SESSION_METRICS') || s.toUpperCase().includes('FROM "SESSION_METRICS"')) {
      const businessId = params && typeof params[0] === 'string' ? params[0] : 'ecommerce';
      const mockMetrics = [
        {
          id: 'm_1',
          business_id: businessId,
          thread_id: 't_1',
          total_tokens: 4200,
          calculated_cost_usd: 0.00063,
          node_transitions_count: 5,
          resolution_status: 'resolved_auto',
          avg_latency_ms: 3200,
          created_at: new Date(Date.now() - 3600000).toISOString(),
        },
        {
          id: 'm_2',
          business_id: businessId,
          thread_id: 't_2',
          total_tokens: 8900,
          calculated_cost_usd: 0.001335,
          node_transitions_count: 6,
          resolution_status: 'waiting_approval',
          avg_latency_ms: 4500,
          created_at: new Date(Date.now() - 7200000).toISOString(),
        },
        {
          id: 'm_3',
          business_id: businessId,
          thread_id: 't_3',
          total_tokens: 3100,
          calculated_cost_usd: 0.000465,
          node_transitions_count: 4,
          resolution_status: 'resolved_auto',
          avg_latency_ms: 2800,
          created_at: new Date(Date.now() - 10800000).toISOString(),
        },
      ];
      return { rows: mockMetrics } as DBQueryResult<unknown>;
    }

    if (s.toUpperCase().includes('FROM RAG_DOCUMENTS') || s.toUpperCase().includes('FROM "RAG_DOCUMENTS"')) {
      const businessId = params && typeof params[0] === 'string' ? params[0] : 'ecommerce';
      const mockEmbedding = JSON.stringify(new Array(1536).fill(0.01)); // Mock 1536-dim standard embedding
      const fakeRags = [
        {
          id: 'fake_rag_1',
          business_id: 'ecommerce',
          chunk_text:
            '对于我们电商主站的订单，普通用户享有自签收之日起 7 天无理由退换货权益。退回的商品必须保持吊牌完整、未拆封且不影响二次销售。非质量问题的退货由买家自行承担寄回运费。',
          contextual_summary: '这段切片描述了电商主站（ecommerce）标准 7 天无理由退换货的前提条件与退货运费归属政策。',
          embedding: mockEmbedding,
        },
        {
          id: 'fake_rag_2',
          business_id: 'nike',
          chunk_text:
            'Nike 会员专属福利：支持自订单购买之日起 30 天超长无理由退换货。即使已经拆除吊牌或进行过试穿，只要鞋底无明显磨损，均可享受免费原路退款。退款通过顺丰速运免费寄回。',
          contextual_summary:
            '这段切片详细说明了 Nike 会员尊享的 30 天无损无理由退货、已拆吊牌退货政策以及顺丰寄回服务。',
          embedding: mockEmbedding,
        },
        {
          id: 'fake_rag_3',
          business_id: 'adidas',
          chunk_text:
            'Adidas 支持签收后 14 天退换货。所有商品必须保留原始包装盒与防伪扣，试穿时请勿弄脏鞋底。退货需要通过官方微信小程序预约快递员上门取件，不支持自行寄送。',
          contextual_summary:
            '这段切片详细规定了 Adidas 的 14 天退换货时效、原始防伪包装要求，以及微信小程序预约取件的硬性物流约束。',
          embedding: mockEmbedding,
        },
      ];
      const rows = fakeRags.filter((r) => r.business_id === businessId);
      return { rows } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes('INSERT INTO RAG_DOCUMENTS') ||
      s.toUpperCase().includes('INSERT INTO "RAG_DOCUMENTS"')
    ) {
      return { rows: [] };
    }

    if (s.toUpperCase().includes('FROM MESSAGES') || s.toUpperCase().includes('FROM "MESSAGES"')) {
      const threadId = params && typeof params[0] === 'string' ? params[0] : '';
      const rows = memoryDb.messages.filter((m) => m.thread_id === threadId);
      return { rows } as DBQueryResult<unknown>;
    }

    if (s.toUpperCase().includes('INSERT INTO MESSAGES') || s.toUpperCase().includes('INSERT INTO "MESSAGES"')) {
      if (params && params.length >= 5) {
        const id = String(params[0]);
        const thread_id = String(params[1]);
        const role = String(params[2]);
        const rawContent = params[3];
        const content = rawContent !== undefined && rawContent !== null ? String(rawContent) : '';
        const timestamp = String(params[4]);
        const msg = { id, thread_id, role, content, timestamp };
        if (!memoryDb.messages.some((m) => m.id === id)) {
          memoryDb.messages.push(msg);
        }

        // 自动确保在内存数据库中创建对应的会话（Thread），让左侧历史会话列表可以动态显示！
        if (!memoryDb.threads.has(thread_id)) {
          memoryDb.threads.set(thread_id, {
            id: thread_id,
            userId: 'u_default_id',
            businessId: 'ecommerce',
            status: 'active',
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          });
        }
      }
      return { rows: [] };
    }

    if (s.toUpperCase().includes('FROM PENDING_APPROVALS') || s.toUpperCase().includes('FROM "PENDING_APPROVALS"')) {
      return { rows: memoryDb.pendingApprovals } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes('INSERT INTO PENDING_APPROVALS') ||
      s.toUpperCase().includes('INSERT INTO "PENDING_APPROVALS"')
    ) {
      if (params && params.length >= 6) {
        const id = String(params[0]);
        const threadId = String(params[1]);
        const actionType = String(params[2]);
        const actionPayloadRaw = params[3];
        const actionPayload = typeof actionPayloadRaw === 'string' ? JSON.parse(actionPayloadRaw) : actionPayloadRaw;
        const status = String(params[4]);
        const deadline = String(params[5]);
        const newApproval = {
          id,
          threadId,
          thread_id: threadId,
          actionType,
          action_type: actionType,
          actionPayload,
          action_payload: actionPayload,
          status,
          deadline,
          createdAt: new Date().toISOString(),
          created_at: new Date().toISOString(),
        };
        memoryDb.pendingApprovals.push(newApproval);
        console.log(`[DB Emulator] Inserted pending approval: ID ${id} for thread ${threadId}`);
      }
      return { rows: [] };
    }

    if (
      s.toUpperCase().includes('UPDATE') &&
      (s.toUpperCase().includes('PENDING_APPROVALS') || s.toUpperCase().includes('"PENDING_APPROVALS"'))
    ) {
      const id = params && params.length > 0 ? (params[params.length - 1] as string) : '';
      const approval = memoryDb.pendingApprovals.find((a) => a.id === id);
      if (approval && params) {
        if (params.length === 2) {
          approval.status = String(params[0]);
        } else if (params.length === 3) {
          approval.status = String(params[0]);
          const payloadRaw = params[1];
          const payload = typeof payloadRaw === 'string' ? JSON.parse(payloadRaw) : payloadRaw;
          approval.actionPayload = payload;
          approval.action_payload = payload;
        }
        console.log(`[DB Emulator] Updated pending approval ID ${id} -> status: ${approval.status}`);
      }
      return { rows: [] };
    }

    if (s.toUpperCase().includes('FROM THREADS') || s.toUpperCase().includes('FROM "THREADS"')) {
      let threadId = params && typeof params[0] === 'string' ? params[0] : '';
      if (!threadId) {
        const threadIdMatch = s.match(/id\s*=\s*['"]([^'"]+)['"]/i);
        if (threadIdMatch) {
          threadId = threadIdMatch[1];
        }
      }
      const thread = memoryDb.threads.get(threadId);
      if (thread) {
        return {
          rows: [
            {
              id: thread.id,
              userId: thread.userId,
              user_id: thread.userId,
              businessId: thread.businessId,
              business_id: thread.businessId,
              status: thread.status,
              createdAt: thread.createdAt,
              created_at: thread.createdAt,
              updatedAt: thread.updatedAt,
              updated_at: thread.updatedAt,
            },
          ],
        };
      }
      return { rows: [] };
    }

    if (
      s.toUpperCase().includes('UPDATE') &&
      (s.toUpperCase().includes('ORDERS') || s.toUpperCase().includes('"ORDERS"'))
    ) {
      let id = params && typeof params[0] === 'string' ? params[0] : '';
      if (!id) {
        const match =
          s.match(/WHERE\s+["']?orderId["']?\s*=\s*['"]([^'"]+)['"]/i) ||
          s.match(/WHERE\s+["']?order_id["']?\s*=\s*['"]([^'"]+)['"]/i);
        id = match ? match[1] : '';
      }
      if (id) {
        const order = memoryDb.orders.get(id);
        if (order) {
          order.status = 'refunded';
          memoryDb.orders.set(id, order);
        }
      }
      return { rows: [] };
    }

    return { rows: [] };
  }
}

let pgPool: Pool | FakePool | null = null;
let drizzleDb: NodePgDatabase<typeof schema> | null = null;
let isUsingRealDb = false;

function getPgPool(): Pool | FakePool {
  if (pgPool) return pgPool;

  const dbUrl = process.env.DATABASE_URL;
  if (dbUrl) {
    try {
      console.log(`[DB] 正在尝试物理连接至 PostgreSQL 数据库: ${dbUrl.replace(/:([^:@]+)@/, ':****@')}...`);
      pgPool = new Pool({
        connectionString: dbUrl,
        connectionTimeoutMillis: 1500, // 1.5秒快速连接超时
      });
      isUsingRealDb = true;
      console.log('[DB] ✅ 物理 PostgreSQL 数据库连接池初始化成功！');
      return pgPool;
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.warn(`[DB] ⚠️ 物理 PostgreSQL 连接失败 (${errMsg})。`);
    }
  }

  console.log('[DB] 🚀 高保真内存物理仿真数据库已就地成功激活！');
  pgPool = new FakePool();
  isUsingRealDb = false;
  return pgPool;
}

export function getDrizzle(): NodePgDatabase<typeof schema> | null {
  if (drizzleDb) return drizzleDb;
  const pool = getPgPool();
  if (pool) {
    try {
      const { drizzle } = require('drizzle-orm/node-postgres');
      drizzleDb = drizzle(pool as Pool, { schema });
    } catch (err) {
      console.error('[DB] Failed to construct drizzle db:', err);
    }
  }
  return drizzleDb;
}

export interface DBExecutorResult {
  rows: unknown[];
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

  // 新增：和用户关联的账户及会话管理接口
  findOrCreateUserByEmail: (email: string) => Promise<{ id: string; email: string }>;
  getUserThreads: (userId: string) => Promise<DBThread[]>;
  createThread: (threadId: string, userId: string) => Promise<DBThread>;
}

async function resolveAndEnsurePgUserId(pool: any, userId: string): Promise<string> {
  const isValidUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(userId);
  if (isValidUuid) {
    return userId;
  }

  try {
    const hash = require('node:crypto').createHash('md5').update(userId).digest('hex');
    const detUuid = `${hash.substring(0, 8)}-${hash.substring(8, 12)}-${hash.substring(12, 16)}-${hash.substring(16, 20)}-${hash.substring(20, 32)}`;

    await pool.query('INSERT INTO users (id, email, created_at) VALUES ($1, $2, NOW()) ON CONFLICT (id) DO NOTHING', [
      detUuid,
      `${userId}@guest.system`,
    ]);
    return detUuid;
  } catch (err) {
    console.warn('[DB] resolveAndEnsurePgUserId failed, falling back to first physical user:', err);
    try {
      const userRes = await pool.query('SELECT id FROM users LIMIT 1');
      if (userRes.rows && userRes.rows.length > 0) {
        return (userRes.rows[0] as any).id;
      }
    } catch (fallbackErr) {
      console.error('[DB] Fallback user lookup failed:', fallbackErr);
    }
    return require('node:crypto').randomUUID();
  }
}

export const db: DBInterface = {
  select: (): DBInterface => db,
  insert: (): DBInterface => db,
  update: (): DBInterface => db,
  delete: (): DBInterface => db,
  values: (): DBInterface => db,

  findOrCreateUserByEmail: async (email: string): Promise<{ id: string; email: string }> => {
    const pool = getPgPool();
    if (isUsingRealDb) {
      try {
        const selectRes = await pool.query('SELECT id, email FROM users WHERE LOWER(email) = LOWER($1) LIMIT 1', [
          email,
        ]);
        if (selectRes.rows && selectRes.rows.length > 0) {
          const row = selectRes.rows[0] as any;
          return { id: row.id, email: row.email };
        }

        // Generate UUID for real user
        const id = crypto.randomUUID ? crypto.randomUUID() : require('node:crypto').randomUUID();
        await pool.query('INSERT INTO users (id, email, created_at) VALUES ($1, $2, NOW())', [id, email]);
        console.log(`[DB User PG] Registered physical user with email: ${email}, ID: ${id}`);

        return { id, email };
      } catch (err) {
        console.error('[DB User PG Error] Failed to find or create user, falling back to memory:', err);
      }
    }

    // 🔍 兼容低版本目标下 MapIterator 遍历报错，使用 Array.from() 彻底化解编译异常！
    const userArray = Array.from(memoryDb.users.values());
    for (const u of userArray) {
      if (u.email.toLowerCase() === email.toLowerCase()) {
        return { id: u.id, email: u.email };
      }
    }
    // 没找到则动态注册
    const id = `u_${Math.random().toString(36).substr(2, 9)}`;
    const newUser = { id, email, createdAt: new Date().toISOString() };
    memoryDb.users.set(id, newUser);
    console.log(`[DB User] Registered new user with email: ${email}, ID: ${id}`);

    return { id, email };
  },

  getUserThreads: async (userId: string): Promise<DBThread[]> => {
    const pool = getPgPool();
    if (isUsingRealDb) {
      try {
        const pgUserId = await resolveAndEnsurePgUserId(pool, userId);

        const res = await pool.query(
          'SELECT id, "user_id" AS "userId", "business_id" AS "businessId", status, "created_at" AS "createdAt", "updated_at" AS "updatedAt" FROM threads WHERE "user_id" = $1 ORDER BY "created_at" DESC',
          [pgUserId],
        );
        return res.rows.map((row: any) => ({
          id: row.id,
          userId: row.userId || row.user_id,
          businessId: row.businessId || row.business_id,
          status: row.status,
          createdAt: row.createdAt || row.created_at,
          updatedAt: row.updatedAt || row.updated_at,
        })) as DBThread[];
      } catch (err) {
        console.error('[DB Thread PG Error] Failed to get user threads, falling back to memory:', err);
      }
    }

    const threadArray = Array.from(memoryDb.threads.values());
    const list = threadArray.filter((t) => t.userId === userId);
    // 按照创建时间降序，保证最新的会话排在最上面！
    return list.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  },

  createThread: async (threadId: string, userId: string): Promise<DBThread> => {
    const pool = getPgPool();
    if (isUsingRealDb) {
      try {
        const pgUserId = await resolveAndEnsurePgUserId(pool, userId);

        await pool.query(
          'INSERT INTO threads (id, "user_id", "business_id", status, "created_at", "updated_at") VALUES ($1, $2, $3, $4, NOW(), NOW()) ON CONFLICT (id) DO NOTHING',
          [threadId, pgUserId, 'ecommerce', 'active'],
        );
        console.log(`[DB Thread PG] Created/Ensured physical thread ${threadId} for mapped user ${pgUserId}`);
        return {
          id: threadId,
          userId: pgUserId,
          businessId: 'ecommerce',
          status: 'active',
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        };
      } catch (err) {
        console.error('[DB Thread PG Error] Failed to create thread, falling back to memory:', err);
      }
    }

    const newThread = {
      id: threadId,
      userId,
      businessId: 'ecommerce',
      status: 'active',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    memoryDb.threads.set(threadId, newThread);
    console.log(`[DB Thread] Created new session thread ${threadId} for user ${userId}`);
    return { ...newThread };
  },

  getMessages: async (threadId: string): Promise<Message[]> => {
    const pool = getPgPool();
    try {
      const res = await pool.query(
        'SELECT id, "thread_id" AS "threadId", role, content, timestamp FROM messages WHERE "thread_id" = $1 ORDER BY timestamp ASC',
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
        threadId: r.thread_id || r.threadId || '',
        role: r.role,
        content: r.content,
        timestamp: r.timestamp,
      })) as Message[];
    } catch (err) {
      console.error('[DB] Failed to get messages:', err);
      return [];
    }
  },

  addMessage: async (message: Message): Promise<void> => {
    const pool = getPgPool();
    try {
      await pool.query(`INSERT INTO messages (id, "thread_id", role, content, timestamp) VALUES ($1, $2, $3, $4, $5)`, [
        message.id,
        message.threadId,
        message.role,
        message.content,
        message.timestamp,
      ]);
    } catch (err) {
      console.error('[DB] Error inserting message:', err);
    }
  },

  getOrder: async (orderId: string): Promise<Order | null> => {
    const pool = getPgPool();
    try {
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
          orderId: row.order_id || row.orderId || '',
          status: row.status,
          carrier: row.carrier,
          trackingNumber: row.tracking_number || row.trackingNumber || '',
          estimatedDelivery: row.estimated_delivery || row.estimatedDelivery || '',
        } as Order;
      }
      return null;
    } catch (err) {
      console.error('[DB] Failed to get order:', err);
      return null;
    }
  },

  execute: async (queryStr: string, params?: unknown[]): Promise<DBExecutorResult> => {
    const pool = getPgPool();
    try {
      const res = await pool.query(queryStr, params);
      return { rows: res.rows as unknown[] };
    } catch (e) {
      console.error('[DB] execute failed:', e);
      return { rows: [] };
    }
  },
};
