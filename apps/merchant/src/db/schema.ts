import { boolean, integer, jsonb, numeric, pgTable, text, timestamp, uuid } from 'drizzle-orm/pg-core';

/**
 * 商户 SPU 表 (Standard Product Unit - 标准产品单元)
 * 定义商品核心信息、规格维度矩阵与通用规格参数
 */
export const merchantSpus = pgTable('merchant_spus', {
  id: uuid('id').primaryKey().defaultRandom(),
  spuCode: text('spu_code').notNull().unique(), // SPU 唯一编码，如 SPU-AURORA-001
  title: text('title').notNull(),
  subtitle: text('subtitle'),
  description: text('description'),
  category: text('category').notNull().default('服装鞋包'),
  brand: text('brand').notNull().default('AURORA 极光'),
  mainImage: text('main_image').notNull(),
  bannerImages: jsonb('banner_images').$type<string[]>().default([]),
  // 规格维度定义：[ { name: "颜色", values: ["曜石黑", "极夜绿"] }, { name: "尺码", values: ["M", "L", "XL"] } ]
  specDimensions: jsonb('spec_dimensions').$type<Array<{ name: string; values: string[] }>>().default([]),
  // 材质与技术参数：{ "面料": "GORE-TEX 3L", "防水指数": "20000mmH2O", "透气指数": "15000g/m²/24h" }
  specs: jsonb('specs').$type<Record<string, string>>().default({}),
  status: text('status').notNull().default('ON_SALE'), // ON_SALE, OFF_SHELF
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

/**
 * 商户 SKU 表 (Stock Keeping Unit - 库存量单元)
 * 精确到单一规格组合的物理库存、独立定价、条形码
 */
export const merchantSkus = pgTable('merchant_skus', {
  id: uuid('id').primaryKey().defaultRandom(),
  spuId: uuid('spu_id')
    .notNull()
    .references(() => merchantSpus.id, { onDelete: 'cascade' }),
  skuCode: text('sku_code').notNull().unique(), // SKU 编码，如 AURORA-SKU-001-BLK-L
  skuTitle: text('sku_title').notNull(), // 如: 极光三合一冲锋衣 曜石黑 L码
  // 规格属性快照映射：{ "颜色": "曜石黑", "尺码": "L (175/92A)" }
  specAttributes: jsonb('spec_attributes').$type<Record<string, string>>().notNull(),
  price: numeric('price', { precision: 10, scale: 2 }).notNull(),
  originalPrice: numeric('original_price', { precision: 10, scale: 2 }),
  stock: integer('stock').notNull().default(0),
  lockedStock: integer('locked_stock').notNull().default(0), // 下单未支付锁库存
  imageUrl: text('image_url'),
  barcode: text('barcode'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

/**
 * 商户自建客户档案表
 */
export const merchantCustomers = pgTable('merchant_customers', {
  id: uuid('id').primaryKey().defaultRandom(),
  customerId: text('customer_id').notNull().unique(), // 如 CUST-8801
  name: text('name').notNull(),
  phone: text('phone').notNull(),
  email: text('email'),
  memberLevel: text('member_level').notNull().default('VIP'),
  addresses: jsonb('addresses')
    .$type<
      Array<{
        id: string;
        recipientName: string;
        phone: string;
        fullAddress: string;
        isDefault?: boolean;
      }>
    >()
    .default([]),
  tags: jsonb('tags').$type<string[]>().default([]),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

/**
 * 商户订单主表
 */
export const merchantOrders = pgTable('merchant_orders', {
  id: uuid('id').primaryKey().defaultRandom(),
  orderId: text('order_id').notNull().unique(), // 如 AURORA-ORD-2026-9081
  customerId: text('customer_id').notNull(),
  status: text('status').notNull().default('PAID'), // PENDING, PAID, PROCESSING, SHIPPED, DELIVERED, CANCELLED, REFUNDED
  totalAmount: numeric('total_amount', { precision: 10, scale: 2 }).notNull(),
  currency: text('currency').notNull().default('CNY'),
  shippingAddress: jsonb('shipping_address')
    .$type<{
      recipientName: string;
      phone: string;
      fullAddress: string;
    }>()
    .notNull(),
  trackingInfo: jsonb('tracking_info').$type<{
    carrier: string;
    trackingNumber: string;
    status: string;
    latestLocation?: string;
    timeline?: Array<{
      time: string;
      status: string;
      location?: string;
      description?: string;
    }>;
  }>(),
  isReturnable: boolean('is_returnable').notNull().default(true),
  isAddressModifiable: boolean('is_address_modifiable').notNull().default(true),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

/**
 * 商户订单明细行表 (记录下单时刻选中的精确 SPU & SKU 及快照)
 */
export const merchantOrderItems = pgTable('merchant_order_items', {
  id: uuid('id').primaryKey().defaultRandom(),
  orderId: text('order_id')
    .notNull()
    .references(() => merchantOrders.orderId, { onDelete: 'cascade' }),
  spuId: text('spu_id').notNull(),
  skuCode: text('sku_code').notNull(),
  title: text('title').notNull(),
  skuTitle: text('sku_title').notNull(),
  quantity: integer('quantity').notNull().default(1),
  price: numeric('price', { precision: 10, scale: 2 }).notNull(),
  imageUrl: text('image_url'),
  specSummary: text('spec_summary'), // 如 "曜石黑 / L码"
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

/**
 * 商户 SPI 开放操作审计流水表
 */
export const merchantAuditLogs = pgTable('merchant_audit_logs', {
  id: uuid('id').primaryKey().defaultRandom(),
  actionType: text('action_type').notNull(), // MODIFY_ADDRESS, CANCEL_ORDER, REQUEST_REFUND, SHIP_ORDER
  orderId: text('order_id').notNull(),
  idempotencyKey: text('idempotency_key').notNull().unique(),
  operator: text('operator').notNull().default('AGENT_SPI'),
  payload: jsonb('payload').$type<Record<string, unknown>>().default({}),
  result: jsonb('result').$type<Record<string, unknown>>().default({}),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});
