import { getPgPool } from './client';

export async function migrateMallTables() {
  const pool = getPgPool();
  console.log('[DB Migration] 正在检查并创建商城完整数据物理表...');

  await pool.query(`
    -- 1. 用户收货地址薄
    CREATE TABLE IF NOT EXISTS user_addresses (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      business_id TEXT NOT NULL,
      user_id TEXT NOT NULL,
      receiver_name TEXT NOT NULL,
      receiver_phone TEXT NOT NULL,
      province TEXT NOT NULL,
      city TEXT NOT NULL,
      district TEXT NOT NULL,
      detail_address TEXT NOT NULL,
      full_address TEXT NOT NULL,
      tag TEXT DEFAULT 'home',
      is_default BOOLEAN DEFAULT false,
      created_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS user_address_biz_user_idx ON user_addresses (business_id, user_id);

    -- 2. 商品多规格物理库存表
    CREATE TABLE IF NOT EXISTS product_skus (
      id TEXT PRIMARY KEY,
      business_id TEXT NOT NULL,
      product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      sku_code TEXT NOT NULL,
      spec_attributes JSONB NOT NULL,
      price REAL NOT NULL,
      cost_price REAL DEFAULT 0.0,
      stock INTEGER DEFAULT 0,
      image_url TEXT,
      status TEXT DEFAULT 'active',
      created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS product_skus_biz_product_idx ON product_skus (business_id, product_id);
    CREATE INDEX IF NOT EXISTS product_skus_code_idx ON product_skus (sku_code);

    -- 3. 包裹主表
    CREATE TABLE IF NOT EXISTS logistics_packages (
      id TEXT PRIMARY KEY,
      business_id TEXT NOT NULL,
      order_id TEXT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
      carrier TEXT NOT NULL,
      carrier_code TEXT NOT NULL,
      tracking_number TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'in_transit',
      current_location TEXT,
      courier_name TEXT,
      courier_phone TEXT,
      estimated_delivery TIMESTAMP,
      created_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS logistics_pkg_biz_order_idx ON logistics_packages (business_id, order_id);
    CREATE INDEX IF NOT EXISTS logistics_pkg_tracking_idx ON logistics_packages (tracking_number);

    -- 4. 物流时序流水表
    CREATE TABLE IF NOT EXISTS logistics_tracks (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      package_id TEXT NOT NULL REFERENCES logistics_packages(id) ON DELETE CASCADE,
      occurred_at TIMESTAMP NOT NULL,
      location TEXT NOT NULL,
      status TEXT NOT NULL,
      description TEXT NOT NULL,
      created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS logistics_tracks_pkg_time_idx ON logistics_tracks (package_id, occurred_at);

    -- 5. 商品评价与口碑表
    CREATE TABLE IF NOT EXISTS product_reviews (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      business_id TEXT NOT NULL,
      product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
      sku_id TEXT,
      order_id TEXT,
      user_id TEXT NOT NULL,
      user_name TEXT,
      user_avatar TEXT,
      rating INTEGER NOT NULL,
      content TEXT NOT NULL,
      images JSONB,
      fit_feedback TEXT,
      sentiment TEXT DEFAULT 'positive',
      merchant_reply TEXT,
      created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS product_reviews_biz_product_idx ON product_reviews (business_id, product_id);

    -- 6. 售后退款退换货工单表
    CREATE TABLE IF NOT EXISTS after_sale_tickets (
      id TEXT PRIMARY KEY,
      business_id TEXT NOT NULL,
      order_id TEXT NOT NULL REFERENCES orders(order_id),
      order_item_id TEXT,
      user_id TEXT NOT NULL,
      type TEXT NOT NULL,
      reason TEXT NOT NULL,
      reason_description TEXT,
      refund_amount REAL NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending_review',
      return_tracking_number TEXT,
      human_approval_id UUID,
      created_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS after_sale_biz_order_idx ON after_sale_tickets (business_id, order_id);
    CREATE INDEX IF NOT EXISTS after_sale_biz_user_idx ON after_sale_tickets (business_id, user_id);

    -- 7. 售后状态流水表
    CREATE TABLE IF NOT EXISTS after_sale_logs (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      ticket_id TEXT NOT NULL REFERENCES after_sale_tickets(id) ON DELETE CASCADE,
      action TEXT NOT NULL,
      operator TEXT NOT NULL,
      note TEXT,
      created_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS after_sale_logs_ticket_idx ON after_sale_logs (ticket_id);
  `);

  console.log('✅ [DB Migration] 商城物理数据表结构创建与迁移完成！');
}

if (import.meta.main) {
  migrateMallTables()
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('❌ [DB Migration] Error migrating mall tables:', err);
      process.exit(1);
    });
}
