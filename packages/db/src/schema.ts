import {
  boolean,
  index,
  integer,
  jsonb,
  pgTable,
  real,
  text,
  timestamp,
  uuid,
} from "drizzle-orm/pg-core";

// ============ 用户与会话 ============

export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  email: text("email").unique(),
  createdAt: timestamp("created_at").defaultNow(),
});

export const threads = pgTable("threads", {
  id: text("id").primaryKey(), // 对应LangGraph的thread_id
  userId: uuid("user_id").references(() => users.id),
  businessId: text("business_id").notNull(), // 对应哪个业务场景(ecommerce/legal...)
  status: text("status").default("active"), // active/completed/abandoned
  createdAt: timestamp("created_at").defaultNow(),
  updatedAt: timestamp("updated_at").defaultNow(),
});

export const messages = pgTable("messages", {
  id: text("id").primaryKey(),
  threadId: text("thread_id")
    .references(() => threads.id)
    .notNull(),
  role: text("role").notNull(), // user / assistant / system
  content: text("content").notNull(),
  timestamp: text("timestamp").notNull(),
});

export const orders = pgTable("orders", {
  orderId: text("order_id").primaryKey(),
  status: text("status").notNull(),
  carrier: text("carrier").notNull(),
  trackingNumber: text("tracking_number").notNull(),
  estimatedDelivery: text("estimated_delivery").notNull(),
  userId: text("user_id"), // 关联用户，支持 SaaS 级归属权控制
  businessId: text("business_id").notNull(), // 关联商户（SaaS 租户隔离，如 nike / adidas）
  totalAmount: real("total_amount"), // 订单总金额
});

// ============ Products (商品物理表 - SaaS 租户级管理) ============

export const products = pgTable("products", {
  id: text("id").primaryKey(),
  businessId: text("business_id").notNull(), // 隔离控制，确保 Adidas 无法查到 Nike 的货
  managerId: text("manager_id"), // 负责人 / 运营专家 ID，支持“我负责的商品”精细化数据权限
  name: text("name").notNull(), // 商品名称
  category: text("category").default("general"), // 商品品类 (如 shoes, apparel, equipment)
  description: text("description"), // 详细描述
  price: real("price").notNull(), // 商品销售单价 (Revenue Price)
  costPrice: real("cost_price").default(0.0), // 商品进货/物料成本单价 (Cost Price，用于利润核算)
  stock: integer("stock").default(99), // 商品物理库存
  createdAt: timestamp("created_at").defaultNow(),
});

// ============ Order Items (订单商品明细关联表 - Relational Normalization) ============

export const orderItems = pgTable("order_items", {
  id: text("id").primaryKey(),
  orderId: text("order_id")
    .references(() => orders.orderId)
    .notNull(),
  productId: text("product_id")
    .references(() => products.id)
    .notNull(),
  quantity: integer("quantity").notNull(), // 购买数量
  priceAtPurchase: real("price_at_purchase").notNull(), // 下单时售价快照
  costAtPurchase: real("cost_at_purchase").default(0.0), // 下单时成本价快照 (防止调价导致历史毛利失真)
});

// ============ SaaS Billing & Conversational Telemetry (租户账单与分析度量表) ============

export const sessionMetrics = pgTable("session_metrics", {
  id: uuid("id").primaryKey().defaultRandom(),
  businessId: text("business_id").notNull(), // SaaS 商户隔离统计
  threadId: text("thread_id")
    .references(() => threads.id)
    .notNull(),
  totalTokens: integer("total_tokens").default(0), // 算力 Token 消耗
  calculatedCostUsd: real("calculated_cost_usd").default(0.0), // 换算财务成本 (USD)
  nodeTransitionsCount: integer("node_transitions_count").default(1), // DAG 图转移深度
  resolutionStatus: text("resolution_status").notNull(), // 'resolved_auto' | 'waiting_approval' | 'expired' | 'cancelled'
  avgLatencyMs: real("avg_latency_ms").default(0), // 本次决策耗时 (毫秒)
  createdAt: timestamp("created_at").defaultNow(),
});

// ============ Long Memory (跨会话事实/偏好) ============

export const longMemoryFacts = pgTable(
  "long_memory_facts",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: text("user_id").notNull(), // 宽松关联对应 userId 字符串
    businessId: text("business_id"), // 商户租户 ID（tenant 级别偏好）
    scope: text("scope").default("global"), // 'global' (客观身体/生理事实) | 'tenant' (特定商户私域偏好)
    fact: text("fact").notNull(), // "用户是前端工程师"
    embedding: text("embedding"),
    type: text("type").default("fact"), // fact / preference / instruction
    confidence: real("confidence").default(1.0), // 智能画像提取置信度评分 (0.0 - 1.0)
    status: text("status").default("approved"), // 状态: approved (已核准) / pending (待核准) / rejected (已驳回)
    source: text("source").default("regex_fallback"), // 事实发现来源渠道
    createdAt: timestamp("created_at").defaultNow(),
    lastUsedAt: timestamp("last_used_at"), // 用于遗忘策略/权重衰减
  },
  (table) => ({
    userScopeBizIdx: index("long_facts_user_scope_biz_idx").on(
      table.userId,
      table.scope,
      table.businessId,
    ),
  }),
);

// ============ Task Memory (多意图队列/任务进度) ============

export const taskMemory = pgTable("task_memory", {
  id: uuid("id").primaryKey().defaultRandom(),
  threadId: text("thread_id")
    .references(() => threads.id)
    .notNull(),
  pendingIntents: jsonb("pending_intents").notNull(),
  // [{intent, status, collectedSlots, priority}, ...]
  updatedAt: timestamp("updated_at").defaultNow(),
});

// ============ Episodic Memory (带时间戳的具体事件) ============

export const episodicEvents = pgTable(
  "episodic_events",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: text("user_id").notNull(),
    threadId: text("thread_id").references(() => threads.id),
    businessId: text("business_id"),
    scope: text("scope").default("global"), // 'global' | 'tenant'
    content: text("content").notNull(),
    embedding: text("embedding"),
    importance: integer("importance").default(3), // LLM打分1-10
    timestamp: timestamp("timestamp").defaultNow(),
  },
  (table) => ({
    episodicUserScopeBizIdx: index("episodic_user_scope_biz_idx").on(
      table.userId,
      table.scope,
      table.businessId,
    ),
  }),
);

// ============ RAG 知识库 ============

export const ragDocuments = pgTable(
  "rag_documents",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    businessId: text("business_id").notNull(), // 按业务隔离知识库
    sourceUrl: text("source_url"),
    chunkText: text("chunk_text").notNull(),
    contextualSummary: text("contextual_summary"), // Contextual Retrieval用,chunk在全文中的说明
    embedding: text("embedding"),
    metadata: jsonb("metadata"), // {category, updatedAt, ...}
    createdAt: timestamp("created_at").defaultNow(),
  },
  (table) => ({
    businessIdx: index("rag_business_idx").on(table.businessId),
  }),
);

// ============ 意图识别日志(用于复盘优化) ============

export const intentLogs = pgTable("intent_logs", {
  id: uuid("id").primaryKey().defaultRandom(),
  threadId: text("thread_id").references(() => threads.id),
  inputText: text("input_text").notNull(),
  predictedIntents: jsonb("predicted_intents").notNull(), // 支持多意图数组
  method: text("method"), // rule/embedding/llm
  confidence: real("confidence"),
  actualOutcome: text("actual_outcome"), // 后续人工标注的真实意图,用于算准确率
  createdAt: timestamp("created_at").defaultNow(),
});

export const lowConfidenceLogs = pgTable("low_confidence_logs", {
  id: uuid("id").primaryKey().defaultRandom(),
  threadId: text("thread_id").references(() => threads.id),
  inputText: text("input_text").notNull(),
  candidates: jsonb("candidates"),
  reviewed: boolean("reviewed").default(false), // 是否已被人工复核过
  createdAt: timestamp("created_at").defaultNow(),
});

// ============ 人工审批(Human-in-the-loop) ============

export const pendingApprovals = pgTable("pending_approvals", {
  id: uuid("id").primaryKey().defaultRandom(),
  threadId: text("thread_id")
    .references(() => threads.id)
    .notNull(),
  actionType: text("action_type").notNull(), // "refund_approval"
  actionPayload: jsonb("action_payload"),
  status: text("status").default("waiting"), // waiting/approved/rejected/expired
  deadline: timestamp("deadline").notNull(),
  createdAt: timestamp("created_at").defaultNow(),
});

// ============ 事务发件箱 (Transactional Outbox Events) ============

export const approvalOutboxEvents = pgTable(
  "approval_outbox_events",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    approvalId: text("approval_id").notNull(),
    threadId: text("thread_id").notNull(),
    eventType: text("event_type").notNull(), // 'resume_execution' | 'cancel_execution' | 'reject_execution'
    payload: jsonb("payload").notNull(), // { systemPromptText, userId, threadId, nextStatus, jobId }
    status: text("status").default("pending").notNull(), // 'pending' | 'processing' | 'completed' | 'failed'
    retryCount: integer("retry_count").default(0).notNull(),
    errorMessage: text("error_message"),
    createdAt: timestamp("created_at").defaultNow(),
    updatedAt: timestamp("updated_at").defaultNow(),
  },
  (table) => ({
    outboxStatusIdx: index("approval_outbox_status_idx").on(
      table.status,
      table.createdAt,
    ),
    outboxApprovalIdx: index("approval_outbox_approval_idx").on(
      table.approvalId,
    ),
  }),
);

// ============ 业务配置(带版本管理) ============

export const businessConfigs = pgTable(
  "business_configs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    businessId: text("business_id").notNull(),
    version: integer("version").notNull(),
    config: jsonb("config").notNull(), // 完整的business.config.ts内容快照
    isActive: boolean("is_active").default(false),
    createdBy: text("created_by"),
    createdAt: timestamp("created_at").defaultNow(),
  },
  (table) => ({
    uniqueVersion: index("business_config_version_idx").on(
      table.businessId,
      table.version,
    ),
  }),
);

// ============ 评测结果(回归对比) ============

export const evalRuns = pgTable("eval_runs", {
  id: uuid("id").primaryKey().defaultRandom(),
  businessId: text("business_id").notNull(),
  gitCommit: text("git_commit"),
  avgAnswerQuality: real("avg_answer_quality"),
  avgLatencyMs: real("avg_latency_ms"),
  totalCostUsd: real("total_cost_usd"),
  passRate: real("pass_rate"),
  createdAt: timestamp("created_at").defaultNow(),
});

export const evalResults = pgTable("eval_results", {
  id: uuid("id").primaryKey().defaultRandom(),
  runId: uuid("run_id")
    .references(() => evalRuns.id)
    .notNull(),
  caseName: text("case_name").notNull(),
  passed: boolean("passed"),
  metrics: jsonb("metrics"), // {toolAccuracy, answerQuality, latency, cost}
});

// ============ LLM调用日志(成本/延迟追踪) ============

export const llmCallLogs = pgTable(
  "llm_call_logs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    threadId: text("thread_id").references(() => threads.id),
    node: text("node"), // triage/reason/executor...
    model: text("model").notNull(),
    tokensIn: integer("tokens_in"),
    tokensOut: integer("tokens_out"),
    costUsd: real("cost_usd"),
    latencyMs: integer("latency_ms"),
    createdAt: timestamp("created_at").defaultNow(),
  },
  (table) => ({
    threadIdx: index("llm_log_thread_idx").on(table.threadId),
  }),
);

// ============ Job执行记录(BullMQ的业务层映射) ============

export const agentJobs = pgTable("agent_jobs", {
  id: text("id").primaryKey(), // BullMQ job id
  threadId: text("thread_id")
    .references(() => threads.id)
    .notNull(),
  status: text("status").default("pending"), // pending/running/completed/failed
  lastHeartbeatAt: timestamp("last_heartbeat_at"), // 卡死检测用
  errorMessage: text("error_message"),
  startedAt: timestamp("started_at"),
  completedAt: timestamp("completed_at"),
});

// ============ SaaS 多租户组织与配置中心 (SaaS Tenant Hub & IAM) ============

export const tenants = pgTable("tenants", {
  id: uuid("id").primaryKey().defaultRandom(),
  businessId: text("business_id").unique().notNull(), // 对应业务命名空间 (如 nike, anker)
  name: text("name").notNull(),
  planTier: text("plan_tier").default("free").notNull(), // 'free' | 'pro' | 'enterprise'
  status: text("status").default("active").notNull(), // 'active' | 'suspended'
  createdAt: timestamp("created_at").defaultNow(),
});

export const tenantMembers = pgTable("tenant_members", {
  id: uuid("id").primaryKey().defaultRandom(),
  tenantId: uuid("tenant_id")
    .references(() => tenants.id, { onDelete: "cascade" })
    .notNull(),
  userId: uuid("user_id")
    .references(() => users.id, { onDelete: "cascade" })
    .notNull(),
  role: text("role").notNull(), // 'owner' | 'admin' | 'agent'
  createdAt: timestamp("created_at").defaultNow(),
});

export const tenantConfigs = pgTable(
  "tenant_configs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    businessId: text("business_id").notNull(),
    systemPrompt: text("system_prompt"),
    welcomeMessage: text("welcome_message"),
    temperature: real("temperature").default(0.7),
    status: text("status").default("draft").notNull(), // 'draft' | 'published'
    version: integer("version").default(1).notNull(),
    updatedAt: timestamp("updated_at").defaultNow(),
  },
  (table) => ({
    bizStatusIdx: index("tenant_config_biz_status_idx").on(
      table.businessId,
      table.status,
    ),
  }),
);

export const tenantTools = pgTable("tenant_tools", {
  id: uuid("id").primaryKey().defaultRandom(),
  tenantId: uuid("tenant_id")
    .references(() => tenants.id, { onDelete: "cascade" })
    .notNull(),
  name: text("name").notNull(),
  description: text("description"),
  schema: jsonb("schema").notNull(),
  authType: text("auth_type").default("none"), // 'none' | 'bearer' | 'basic' | 'custom_header'
  encryptedCredentials: text("encrypted_credentials"), // AES-256-GCM (iv:tag:cipher)
  requiresApproval: boolean("requires_approval").default(false),
  enabled: boolean("enabled").default(true),
  createdAt: timestamp("created_at").defaultNow(),
});

// ============ User Addresses (用户收货地址薄 - 支持智能选址与改派) ============

export const userAddresses = pgTable(
  "user_addresses",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    businessId: text("business_id").notNull(), // SaaS 租户隔离
    userId: text("user_id").notNull(), // 用户 ID
    receiverName: text("receiver_name").notNull(), // 收件人姓名
    receiverPhone: text("receiver_phone").notNull(), // 联系电话
    province: text("province").notNull(), // 省份
    city: text("city").notNull(), // 城市
    district: text("district").notNull(), // 区县
    detailAddress: text("detail_address").notNull(), // 详细地址
    fullAddress: text("full_address").notNull(), // 完整拼接地址（便于向量化检索与LLM直读）
    tag: text("tag").default("home"), // 'home' | 'company' | 'school' | 'other'
    isDefault: boolean("is_default").default(false), // 是否为默认地址
    createdAt: timestamp("created_at").defaultNow(),
    updatedAt: timestamp("updated_at").defaultNow(),
  },
  (table) => ({
    userBizIdx: index("user_address_biz_user_idx").on(
      table.businessId,
      table.userId,
    ),
  }),
);

// ============ Product SKUs (商品多规格物理库存表 - SKU/Spec) ============

export const productSkus = pgTable(
  "product_skus",
  {
    id: text("id").primaryKey(), // SKU 唯一标识，如 sku_nike_pegasus_blk_42
    businessId: text("business_id").notNull(), // 租户隔离
    productId: text("product_id")
      .references(() => products.id, { onDelete: "cascade" })
      .notNull(),
    skuCode: text("sku_code").notNull(), // 物料条码
    specAttributes: jsonb("spec_attributes").notNull(), // 规格键值对，例如 {"color": "极夜黑", "size": "42"}
    price: real("price").notNull(), // SKU 独立售价
    costPrice: real("cost_price").default(0.0), // SKU 成本价
    stock: integer("stock").default(0), // SKU 独立物理库存
    imageUrl: text("image_url"), // 规格专属主图
    status: text("status").default("active"), // 'active' | 'out_of_stock' | 'discontinued'
    createdAt: timestamp("created_at").defaultNow(),
  },
  (table) => ({
    productSkuBizIdx: index("product_skus_biz_product_idx").on(
      table.businessId,
      table.productId,
    ),
    skuCodeIdx: index("product_skus_code_idx").on(table.skuCode),
  }),
);

// ============ Logistics Packages (包裹主表 - 支持一单多包履约) ============

export const logisticsPackages = pgTable(
  "logistics_packages",
  {
    id: text("id").primaryKey(), // 包裹编号，如 pkg_sf_9876543210
    businessId: text("business_id").notNull(),
    orderId: text("order_id")
      .references(() => orders.orderId, { onDelete: "cascade" })
      .notNull(),
    carrier: text("carrier").notNull(), // 承运商名称，如 '顺丰速运', '京东快递'
    carrierCode: text("carrier_code").notNull(), // 'SF' | 'JD' | 'ZTO' | 'EMS'
    trackingNumber: text("tracking_number").notNull(), // 快递运单号
    status: text("status").default("in_transit").notNull(), // 'pending_pickup' | 'in_transit' | 'delivering' | 'delivered' | 'exception' | 'rejected'
    currentLocation: text("current_location"), // 当前中转站/分拨中心
    courierName: text("courier_name"), // 派件快递员姓名
    courierPhone: text("courier_phone"), // 快递员联系电话
    estimatedDelivery: timestamp("estimated_delivery"), // 预计到达时间
    createdAt: timestamp("created_at").defaultNow(),
    updatedAt: timestamp("updated_at").defaultNow(),
  },
  (table) => ({
    orderPackageIdx: index("logistics_pkg_biz_order_idx").on(
      table.businessId,
      table.orderId,
    ),
    trackingIdx: index("logistics_pkg_tracking_idx").on(table.trackingNumber),
  }),
);

// ============ Logistics Tracks (物流时序节点流水表) ============

export const logisticsTracks = pgTable(
  "logistics_tracks",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    packageId: text("package_id")
      .references(() => logisticsPackages.id, { onDelete: "cascade" })
      .notNull(),
    occurredAt: timestamp("occurred_at").notNull(), // 轨迹发生时间戳
    location: text("location").notNull(), // 所在城市/网点
    status: text("status").notNull(), // 'picked_up' | 'transporting' | 'dispatching' | 'signed' | 'problem'
    description: text("description").notNull(), // 轨迹详细描述信息
    createdAt: timestamp("created_at").defaultNow(),
  },
  (table) => ({
    pkgTrackTimeIdx: index("logistics_tracks_pkg_time_idx").on(
      table.packageId,
      table.occurredAt,
    ),
  }),
);

// ============ Product Reviews (商品真实评价与口碑库) ============

export const productReviews = pgTable(
  "product_reviews",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    businessId: text("business_id").notNull(),
    productId: text("product_id")
      .references(() => products.id, { onDelete: "cascade" })
      .notNull(),
    skuId: text("sku_id"), // 关联的具体规格
    orderId: text("order_id"), // 关联的订单
    userId: text("user_id").notNull(),
    userName: text("user_name"),
    userAvatar: text("user_avatar"),
    rating: integer("rating").notNull(), // 评分 1-5 星
    content: text("content").notNull(), // 评价文本
    images: jsonb("images"), // 晒单图片数组 string[]
    fitFeedback: text("fit_feedback"), // 'true_to_size' (正码) | 'runs_small' (偏小) | 'runs_large' (偏大)
    sentiment: text("sentiment").default("positive"), // 'positive' | 'neutral' | 'negative'
    merchantReply: text("merchant_reply"), // 商家回复内容
    createdAt: timestamp("created_at").defaultNow(),
  },
  (table) => ({
    productReviewBizIdx: index("product_reviews_biz_product_idx").on(
      table.businessId,
      table.productId,
    ),
  }),
);

// ============ After-Sale Tickets (售后退款与退换货工单) ============

export const afterSaleTickets = pgTable(
  "after_sale_tickets",
  {
    id: text("id").primaryKey(), // 售后工单号，如 as_20260821001
    businessId: text("business_id").notNull(),
    orderId: text("order_id")
      .references(() => orders.orderId)
      .notNull(),
    orderItemId: text("order_item_id"),
    userId: text("user_id").notNull(),
    type: text("type").notNull(), // 'refund_only' | 'return_and_refund' | 'exchange'
    reason: text("reason").notNull(), // 'wrong_size' | 'quality_issue' | 'not_as_described' | 'no_reason_7d'
    reasonDescription: text("reason_description"),
    refundAmount: real("refund_amount").notNull(),
    status: text("status").default("pending_review").notNull(), // 'pending_review' | 'approved' | 'rejected' | 'waiting_user_ship' | 'merchant_inspecting' | 'completed' | 'cancelled'
    returnTrackingNumber: text("return_tracking_number"), // 退货物流运单号
    humanApprovalId: uuid("human_approval_id"), // 关联 pendingApprovals.id
    createdAt: timestamp("created_at").defaultNow(),
    updatedAt: timestamp("updated_at").defaultNow(),
  },
  (table) => ({
    afterSaleBizOrderIdx: index("after_sale_biz_order_idx").on(
      table.businessId,
      table.orderId,
    ),
    afterSaleBizUserIdx: index("after_sale_biz_user_idx").on(
      table.businessId,
      table.userId,
    ),
  }),
);

// ============ After-Sale Logs (售后状态流转流水日志) ============

export const afterSaleLogs = pgTable(
  "after_sale_logs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    ticketId: text("ticket_id")
      .references(() => afterSaleTickets.id, { onDelete: "cascade" })
      .notNull(),
    action: text("action").notNull(), // 'created' | 'approved' | 'rejected' | 'shipped_back' | 'refunded'
    operator: text("operator").notNull(), // 'user' | 'agent_autopilot' | 'admin:staff_12'
    note: text("note"),
    createdAt: timestamp("created_at").defaultNow(),
  },
  (table) => ({
    ticketLogIdx: index("after_sale_logs_ticket_idx").on(table.ticketId),
  }),
);

// Keep standard TypeScript Interfaces compatible with other calling workspaces
export interface Message {
  id: string;
  threadId: string;
  role: string;
  content: string;
  timestamp: string;
}

export interface Order {
  orderId: string;
  status: string;
  carrier: string;
  trackingNumber: string;
  estimatedDelivery: string;
}

export interface DBUser {
  id: string;
  name: string;
  email: string;
}
