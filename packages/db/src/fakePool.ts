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
    {
      id: string;
      userId: string;
      businessId: string;
      status: string;
      createdAt: string;
      updatedAt: string;
    }
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
    actionPayload: unknown;
    action_payload: unknown;
    status: string;
    deadline: string;
    createdAt: string;
    created_at: string;
  }>;
  taskMemory: Map<
    string,
    {
      id: string;
      threadId: string;
      pendingIntents: unknown;
      updatedAt: string;
    }
  >;
}

const globalForDb = global as unknown as {
  memoryDb?: MemoryDatabaseState;
};

export const memoryDb: MemoryDatabaseState = globalForDb.memoryDb ?? {
  users: new Map<string, { id: string; email: string; createdAt: string }>([
    [
      "83d67d4e-104c-4325-8aa7-10d4389fc725",
      {
        id: "83d67d4e-104c-4325-8aa7-10d4389fc725",
        email: "test@example.com",
        createdAt: new Date().toISOString(),
      },
    ],
  ]),
  threads: new Map<
    string,
    {
      id: string;
      userId: string;
      businessId: string;
      status: string;
      createdAt: string;
      updatedAt: string;
    }
  >(),
  orders: new Map([
    [
      "ORD-98712",
      {
        order_id: "ORD-98712",
        status: "shipped",
        carrier: "FedEx",
        tracking_number: "1234567890",
        estimated_delivery: "2026-07-20",
        user_id: "83d67d4e-104c-4325-8aa7-10d4389fc725",
        business_id: "nike",
        total_amount: 139.99,
      },
    ],
    [
      "ORD-55555",
      {
        order_id: "ORD-55555",
        status: "completed",
        carrier: "SF Express",
        tracking_number: "SF9876543210",
        estimated_delivery: "2026-07-25",
        user_id: "83d67d4e-104c-4325-8aa7-10d4389fc725",
        business_id: "ecommerce",
        total_amount: 49.99,
      },
    ],
    [
      "ORD-ADIDAS-OK",
      {
        order_id: "ORD-ADIDAS-OK",
        status: "delivered",
        carrier: "SF Express",
        tracking_number: "SF1234567",
        estimated_delivery: "2026-07-22",
        user_id: "83d67d4e-104c-4325-8aa7-10d4389fc725",
        business_id: "adidas",
        total_amount: 12.5,
      },
    ],
    [
      "ORD-ADIDAS-EXPIRED",
      {
        order_id: "ORD-ADIDAS-EXPIRED",
        status: "delivered",
        carrier: "DHL",
        tracking_number: "DHL88712",
        estimated_delivery: "2026-06-10",
        user_id: "83d67d4e-104c-4325-8aa7-10d4389fc725",
        business_id: "adidas",
        total_amount: 179.99,
      },
    ],
  ]),
  products: new Map([
    [
      "prod_nike_1",
      {
        id: "prod_nike_1",
        business_id: "nike",
        name: "Nike Pegasus Trail 5 越野跑鞋",
        description:
          "专为户外越野打造，搭载高强度 React 缓震泡棉，耐磨抓地橡胶大底。",
        price: 139.99,
        stock: 45,
      },
    ],
    [
      "prod_nike_2",
      {
        id: "prod_nike_2",
        business_id: "nike",
        name: "Nike Element 户外防风连帽衫",
        description: "高透气防泼水面料，反光条设计保障夜间户外运动安全。",
        price: 85.0,
        stock: 30,
      },
    ],
    [
      "prod_adidas_1",
      {
        id: "prod_adidas_1",
        business_id: "adidas",
        name: "Adidas Ultraboost 1.0 经典跑鞋",
        description: "卓越的 Boost 能量回馈中底，Primeknit 贴合针织鞋面。",
        price: 179.99,
        stock: 50,
      },
    ],
    [
      "prod_adidas_2",
      {
        id: "prod_adidas_2",
        business_id: "adidas",
        name: "Adidas Multi-Pack 运动专业棉袜 (3双装)",
        description: "吸湿排汗，足弓加厚减震缓冲。",
        price: 12.5,
        stock: 120,
      },
    ],
    [
      "prod_eco_1",
      {
        id: "prod_eco_1",
        business_id: "ecommerce",
        name: "电商主站极绒亲肤抗静电保暖毯",
        description: "高克重复合超细纤维，环保防静电印染，居家车载必备。",
        price: 49.99,
        stock: 85,
      },
    ],
  ]),
  orderItems: [
    {
      id: "item_nike_1",
      order_id: "ORD-98712",
      product_id: "prod_nike_1",
      quantity: 1,
      price_at_purchase: 139.99,
    },
    {
      id: "item_eco_1",
      order_id: "ORD-55555",
      product_id: "prod_eco_1",
      quantity: 1,
      price_at_purchase: 49.99,
    },
    {
      id: "item_adidas_ok_1",
      order_id: "ORD-ADIDAS-OK",
      product_id: "prod_adidas_2",
      quantity: 1,
      price_at_purchase: 12.5,
    },
    {
      id: "item_adidas_exp_1",
      order_id: "ORD-ADIDAS-EXPIRED",
      product_id: "prod_adidas_1",
      quantity: 1,
      price_at_purchase: 179.99,
    },
  ],
  messages: [],
  pendingApprovals: [],
  taskMemory: new Map(),
};

if (process.env.NODE_ENV !== "production") {
  globalForDb.memoryDb = memoryDb;
}

export class FakePool {
  async connect(): Promise<{
    query: (
      queryStr: string | FakeQueryObject,
      params?: unknown[],
    ) => Promise<DBQueryResult<unknown>>;
    release: () => void;
  }> {
    return {
      query: async (
        queryStr: string | FakeQueryObject,
        params?: unknown[],
      ): Promise<DBQueryResult<unknown>> => {
        return this.query(queryStr, params);
      },
      release: (): void => {},
    };
  }

  on(_event: string, _cb: (...args: unknown[]) => void): void {}

  async query(
    queryStr: string | FakeQueryObject,
    params?: unknown[],
  ): Promise<DBQueryResult<unknown>> {
    const sqlText =
      typeof queryStr === "string" ? queryStr : queryStr.text || "";
    const s = sqlText.trim().replace(/\s+/g, " ");

    if (s.toUpperCase().includes("CREATE TABLE")) {
      return { rows: [] };
    }

    if (
      s.toUpperCase().includes("INSERT INTO ORDERS") ||
      s.toUpperCase().includes('INSERT INTO "ORDERS"')
    ) {
      return { rows: [] };
    }

    if (
      s.toUpperCase().includes("FROM ORDERS") ||
      s.toUpperCase().includes('FROM "ORDERS"')
    ) {
      const userMatch =
        s.match(/user_id\s*=\s*['"]([^'"]+)['"]/i) ||
        s.match(/["']?user_id["']?\s*=\s*\$1/i);
      if (userMatch) {
        const userId =
          params && typeof params[0] === "string" ? params[0] : "u_default_id";
        let rows = Array.from(memoryDb.orders.values()).filter(
          (o) => o.user_id === userId,
        );

        const businessMatch = s.match(/["']?business_id["']?\s*=\s*\$2/i);
        if (businessMatch && params && typeof params[1] === "string") {
          const businessId = params[1];
          rows = rows.filter((o) => o.business_id === businessId);
        }

        const mappedRows = rows.map((o) => ({
          ...o,
          orderId: o.order_id,
          trackingNumber: o.tracking_number,
          estimatedDelivery: o.estimated_delivery,
          totalAmount: o.total_amount,
          userId: o.user_id,
          businessId: o.business_id,
        }));

        return { rows: mappedRows } as DBQueryResult<unknown>;
      }

      const rawUserMatch = s.match(/["']user_id["']\s*=\s*['"]([^'"]+)['"]/i);
      if (rawUserMatch) {
        const userId = rawUserMatch[1];
        const rows = Array.from(memoryDb.orders.values()).filter(
          (o) => o.user_id === userId,
        );

        const mappedRows = rows.map((o) => ({
          ...o,
          orderId: o.order_id,
          trackingNumber: o.tracking_number,
          estimatedDelivery: o.estimated_delivery,
          totalAmount: o.total_amount,
          userId: o.user_id,
          businessId: o.business_id,
        }));

        return { rows: mappedRows } as DBQueryResult<unknown>;
      }

      let orderId = params && typeof params[0] === "string" ? params[0] : "";
      if (!orderId) {
        const orderIdMatch =
          s.match(/order_id\s*=\s*['"]([^'"]+)['"]/i) ||
          s.match(/orderId\s*=\s*['"]([^'"]+)['"]/i);
        if (orderIdMatch) {
          orderId = orderIdMatch[1];
        }
      }
      const order = orderId ? memoryDb.orders.get(orderId) : null;
      const mappedOrder = order
        ? {
            ...order,
            orderId: order.order_id,
            trackingNumber: order.tracking_number,
            estimatedDelivery: order.estimated_delivery,
            totalAmount: order.total_amount,
            userId: order.user_id,
            businessId: order.business_id,
          }
        : null;
      return {
        rows: mappedOrder ? [mappedOrder] : [],
      } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes("FROM PRODUCTS") ||
      s.toUpperCase().includes('FROM "PRODUCTS"')
    ) {
      const businessId =
        params && typeof params[0] === "string" ? params[0] : "nike";
      const rows = Array.from(memoryDb.products.values()).filter(
        (p) => p.business_id === businessId,
      );
      return { rows } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes("FROM ORDER_ITEMS") ||
      s.toUpperCase().includes('FROM "ORDER_ITEMS"')
    ) {
      let orderId = params && typeof params[0] === "string" ? params[0] : "";
      if (!orderId) {
        const orderIdMatch =
          s.match(/order_id\s*=\s*['"]([^'"]+)['"]/i) ||
          s.match(/orderId\s*=\s*['"]([^'"]+)['"]/i);
        if (orderIdMatch) {
          orderId = orderIdMatch[1];
        }
      }
      const rows = orderId
        ? memoryDb.orderItems.filter((item) => item.order_id === orderId)
        : [];
      return { rows } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes("FROM SESSION_METRICS") ||
      s.toUpperCase().includes('FROM "SESSION_METRICS"')
    ) {
      const businessId =
        params && typeof params[0] === "string" ? params[0] : "ecommerce";
      const mockMetrics = [
        {
          id: "m_1",
          business_id: businessId,
          thread_id: "t_1",
          total_tokens: 4200,
          calculated_cost_usd: 0.00063,
          node_transitions_count: 5,
          resolution_status: "resolved_auto",
          avg_latency_ms: 3200,
          created_at: new Date(Date.now() - 3600000).toISOString(),
        },
      ];
      return { rows: mockMetrics } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes("FROM RAG_DOCUMENTS") ||
      s.toUpperCase().includes('FROM "RAG_DOCUMENTS"')
    ) {
      const businessId =
        params && typeof params[0] === "string" ? params[0] : "ecommerce";
      const mockEmbedding = JSON.stringify(new Array(1536).fill(0.01));
      const fakeRags = [
        {
          id: "fake_rag_1",
          business_id: "ecommerce",
          chunk_text:
            "对于我们电商主站的订单，普通用户享有自签收之日起 7 天无理由退换货权益。",
          contextual_summary: "电商主站退换货条件与运费政策。",
          embedding: mockEmbedding,
        },
      ];
      const rows = fakeRags.filter((r) => r.business_id === businessId);
      return { rows } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes("FROM MESSAGES") ||
      s.toUpperCase().includes('FROM "MESSAGES"')
    ) {
      const threadId = params && typeof params[0] === "string" ? params[0] : "";
      const rows = memoryDb.messages.filter((m) => m.thread_id === threadId);
      return { rows } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes("INSERT INTO MESSAGES") ||
      s.toUpperCase().includes('INSERT INTO "MESSAGES"')
    ) {
      if (params && params.length >= 5) {
        const id = String(params[0]);
        const thread_id = String(params[1]);
        const role = String(params[2]);
        const rawContent = params[3];
        const content =
          rawContent !== undefined && rawContent !== null
            ? String(rawContent)
            : "";
        const timestamp = String(params[4]);
        const msg = { id, thread_id, role, content, timestamp };
        if (!memoryDb.messages.some((m) => m.id === id)) {
          memoryDb.messages.push(msg);
        }

        if (!memoryDb.threads.has(thread_id)) {
          memoryDb.threads.set(thread_id, {
            id: thread_id,
            userId: "u_default_id",
            businessId: "ecommerce",
            status: "active",
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
          });
        }
      }
      return { rows: [] };
    }

    if (
      s.toUpperCase().includes("FROM PENDING_APPROVALS") ||
      s.toUpperCase().includes('FROM "PENDING_APPROVALS"')
    ) {
      let threadId = params && typeof params[0] === "string" ? params[0] : "";
      if (!threadId) {
        const threadIdMatch =
          s.match(/thread_id\s*=\s*['"]([^'"]+)['"]/i) ||
          s.match(/threadId\s*=\s*['"]([^'"]+)['"]/i);
        if (threadIdMatch) {
          threadId = threadIdMatch[1];
        }
      }

      let filtered = memoryDb.pendingApprovals;
      if (threadId) {
        filtered = filtered.filter(
          (pa) => pa.threadId === threadId || pa.thread_id === threadId,
        );
      }

      const sorted = [...filtered].sort((a, b) => {
        const dateA = new Date(a.createdAt || a.created_at || 0).getTime();
        const dateB = new Date(b.createdAt || b.created_at || 0).getTime();
        return dateB - dateA;
      });

      return { rows: sorted } as DBQueryResult<unknown>;
    }

    if (
      s.toUpperCase().includes("FROM THREADS") ||
      s.toUpperCase().includes('FROM "THREADS"')
    ) {
      let threadId = params && typeof params[0] === "string" ? params[0] : "";
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
      s.toUpperCase().includes("UPDATE") &&
      (s.toUpperCase().includes("ORDERS") ||
        s.toUpperCase().includes('"ORDERS"'))
    ) {
      let id = params && typeof params[0] === "string" ? params[0] : "";
      if (!id) {
        const match =
          s.match(/WHERE\s+["']?orderId["']?\s*=\s*['"]([^'"]+)['"]/i) ||
          s.match(/WHERE\s+["']?order_id["']?\s*=\s*['"]([^'"]+)['"]/i);
        id = match ? match[1] : "";
      }
      if (id) {
        const order = memoryDb.orders.get(id);
        if (order) {
          order.status = "refunded";
          memoryDb.orders.set(id, order);
        }
      }
      return { rows: [] };
    }

    return { rows: [] };
  }
}
