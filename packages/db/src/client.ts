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
}

// 在内存中模拟一个完整的物理数据库表状态
const memoryDb: MemoryDatabaseState = {
  users: new Map<string, { id: string; email: string; createdAt: string }>([
    ['u_default_id', { id: 'u_default_id', email: 'test@example.com', createdAt: new Date().toISOString() }],
  ]),
  threads: new Map<
    string,
    { id: string; userId: string; businessId: string; status: string; createdAt: string; updatedAt: string }
  >([
    [
      'thread_local_shared',
      {
        id: 'thread_local_shared',
        userId: 'u_default_id',
        businessId: 'ecommerce',
        status: 'active',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      },
    ],
  ]),
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
  ],
  messages: [],
};

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
      const orderId = params && typeof params[0] === 'string' ? params[0] : 'ORD-98712';
      const order = memoryDb.orders.get(orderId);
      return { rows: order ? [order] : [] } as DBQueryResult<unknown>;
    }

    if (s.toUpperCase().includes('FROM PRODUCTS') || s.toUpperCase().includes('FROM "PRODUCTS"')) {
      const businessId = params && typeof params[0] === 'string' ? params[0] : 'nike';
      const rows = Array.from(memoryDb.products.values()).filter((p) => p.business_id === businessId);
      return { rows } as DBQueryResult<unknown>;
    }

    if (s.toUpperCase().includes('FROM ORDER_ITEMS') || s.toUpperCase().includes('FROM "ORDER_ITEMS"')) {
      const orderId = params && typeof params[0] === 'string' ? params[0] : 'ORD-98712';
      const rows = memoryDb.orderItems.filter((item) => item.order_id === orderId);
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
      const fakeRags = [
        {
          id: 'fake_rag_1',
          businessId: 'ecommerce',
          chunkText:
            '对于我们电商主站的订单，普通用户享有自签收之日起 7 天无理由退换货权益。退回的商品必须保持吊牌完整、未拆封且不影响二次销售。非质量问题的退货由买家自行承担寄回运费。',
          contextualSummary: '这段切片描述了电商主站（ecommerce）标准 7 天无理由退换货的前提条件与退货运费归属政策。',
        },
        {
          id: 'fake_rag_2',
          businessId: 'nike',
          chunkText:
            'Nike 会员专属福利：支持自订单购买之日起 30 天超长无理由退换货。即使已经拆除吊牌或进行过试穿，只要鞋底无明显磨损，均可享受免费原路退款。退款通过顺丰速运免费寄回。',
          contextualSummary:
            '这段切片详细说明了 Nike 会员尊享的 30 天无损无理由退货、已拆吊牌退货政策以及顺丰寄回服务。',
        },
        {
          id: 'fake_rag_3',
          businessId: 'adidas',
          chunkText:
            'Adidas 支持签收后 14 天退换货。所有商品必须保留原始包装盒与防伪扣，试穿时请勿弄脏鞋底。退货需要通过官方微信小程序预约快递员上门取件，不支持自行寄送。',
          contextualSummary:
            '这段切片详细规定了 Adidas 的 14 天退换货时效、原始防伪包装要求，以及微信小程序预约取件的硬性物流约束。',
        },
      ];
      const rows = fakeRags.filter((r) => r.businessId === businessId);
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
        const content = String(params[3]);
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

    if (
      s.toUpperCase().includes('UPDATE') &&
      (s.toUpperCase().includes('ORDERS') || s.toUpperCase().includes('"ORDERS"'))
    ) {
      const match = s.match(/WHERE\s+["']?orderId["']?\s*=\s*['"]([^'"]+)['"]/i);
      const id = match ? match[1] : 'ORD-98712';
      const order = memoryDb.orders.get(id);
      if (order) {
        order.status = 'refunded';
        memoryDb.orders.set(id, order);
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
  execute: (queryStr: string) => Promise<DBExecutorResult>;

  // 新增：和用户关联的账户及会话管理接口
  findOrCreateUserByEmail: (email: string) => Promise<{ id: string; email: string }>;
  getUserThreads: (userId: string) => Promise<DBThread[]>;
  createThread: (threadId: string, userId: string) => Promise<DBThread>;
}

export const db: DBInterface = {
  select: (): DBInterface => db,
  insert: (): DBInterface => db,
  update: (): DBInterface => db,
  delete: (): DBInterface => db,
  values: (): DBInterface => db,

  findOrCreateUserByEmail: async (email: string): Promise<{ id: string; email: string }> => {
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

    // 自动为新注册用户初始分配一个默认会话，体验更加平滑！
    const defaultThreadId = `thread_local_${id}`;
    memoryDb.threads.set(defaultThreadId, {
      id: defaultThreadId,
      userId: id,
      businessId: 'ecommerce',
      status: 'active',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });

    return { id, email };
  },

  getUserThreads: async (userId: string): Promise<DBThread[]> => {
    const threadArray = Array.from(memoryDb.threads.values());
    const list = threadArray.filter((t) => t.userId === userId);
    // 按照创建时间降序，保证最新的会话排在最上面！
    return list.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  },

  createThread: async (threadId: string, userId: string): Promise<DBThread> => {
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

  execute: async (queryStr: string): Promise<DBExecutorResult> => {
    const pool = getPgPool();
    try {
      const res = await pool.query(queryStr);
      return { rows: res.rows as unknown[] };
    } catch (e) {
      console.error('[DB] execute failed:', e);
      return { rows: [] };
    }
  },
};
