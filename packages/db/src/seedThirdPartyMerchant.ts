import { getPgPool } from './client';

export async function seedThirdPartyMerchant() {
  const pool = getPgPool();
  console.log('[SeedMerchant] Initializing third-party merchant physical tables and seed data...');

  // 1. 创建第三方物理表结构 (完全独立的商户专属表)
  await pool.query(`
    ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS spi_config JSONB;
    ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS enabled_skills JSONB;

    CREATE TABLE IF NOT EXISTS third_party_customers (
      customer_id TEXT PRIMARY KEY,
      merchant_id TEXT NOT NULL,
      external_email TEXT,
      customer_name TEXT NOT NULL,
      phone_number TEXT,
      vip_tier TEXT DEFAULT 'GOLD',
      delivery_addresses JSONB,
      created_at TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS third_party_orders (
      ext_order_sn TEXT PRIMARY KEY,
      merchant_id TEXT NOT NULL,
      customer_id TEXT NOT NULL,
      order_status TEXT NOT NULL,
      order_currency TEXT DEFAULT 'CNY',
      pay_amount REAL NOT NULL,
      recipient_name TEXT NOT NULL,
      recipient_phone TEXT NOT NULL,
      shipping_address TEXT NOT NULL,
      carrier_code TEXT,
      tracking_no TEXT,
      can_modify_address BOOLEAN DEFAULT TRUE,
      can_refund BOOLEAN DEFAULT TRUE,
      order_time TIMESTAMP DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS third_party_order_items (
      item_id TEXT PRIMARY KEY,
      ext_order_sn TEXT NOT NULL REFERENCES third_party_orders(ext_order_sn) ON DELETE CASCADE,
      sku_code TEXT NOT NULL,
      item_title TEXT NOT NULL,
      unit_price REAL NOT NULL,
      buy_qty INTEGER NOT NULL,
      item_pic_url TEXT
    );

    CREATE TABLE IF NOT EXISTS third_party_inventory (
      sku_code TEXT PRIMARY KEY,
      merchant_id TEXT NOT NULL,
      item_title TEXT NOT NULL,
      category_name TEXT DEFAULT 'fashion',
      selling_price REAL NOT NULL,
      available_qty INTEGER DEFAULT 50,
      is_on_shelf BOOLEAN DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS third_party_audit_logs (
      action_id TEXT PRIMARY KEY,
      merchant_id TEXT NOT NULL,
      ext_order_sn TEXT NOT NULL,
      action_type TEXT NOT NULL,
      idempotency_token TEXT NOT NULL,
      received_signature TEXT,
      payload JSONB,
      executed_at TIMESTAMP DEFAULT NOW()
    );
  `);

  // 1.5 在平台 SaaS 多租户表中动态注册入驻商户 (Dynamic Tenant Registration)
  await pool.query(`
    INSERT INTO tenants (id, business_id, name, plan_tier, status)
    VALUES ('a0000000-0000-0000-0000-000000000001', 'aurora', '极光潮品官方旗舰店', 'enterprise', 'active')
    ON CONFLICT (business_id) DO UPDATE SET
      name = EXCLUDED.name,
      status = EXCLUDED.status;

    INSERT INTO tenant_configs (id, business_id, system_prompt, welcome_message, status, version, spi_config, enabled_skills)
    VALUES (
      'b0000000-0000-0000-0000-000000000001',
      'aurora',
      'You are the official AI Customer Support Agent for 极光潮品 (Aurora Luxe). Help customers with order shipping tracking, fast address modification, refund requests, and product inventory inquiry via remote SPI.',
      '您好！我是极光潮品官方智能客服。请问有什么可以帮您？',
      'published',
      1,
      '{"mode": "remote_spi", "spiBaseUrl": "http://localhost:3005", "apiSecret": "aurora_secret_key_8899", "timeoutMs": 5000}'::jsonb,
      '["skill_order_address_modification", "skill_order_refund", "skill_product_inquiry"]'::jsonb
    )
    ON CONFLICT (id) DO UPDATE SET
      spi_config = EXCLUDED.spi_config,
      system_prompt = EXCLUDED.system_prompt;
  `);

  // 2. 写入极光潮品商户商品数据 (Aurora Fashion Products)
  const products = [
    {
      skuCode: 'AURORA-SKU-001',
      merchantId: 'aurora',
      itemTitle: '极光纯棉重磅短袖T恤 (220g重磅)',
      categoryName: 'apparel',
      sellingPrice: 129.0,
      availableQty: 180,
    },
    {
      skuCode: 'AURORA-SKU-002',
      merchantId: 'aurora',
      itemTitle: '极光轻量三防连帽冲锋衣 (暴雨级防水)',
      categoryName: 'outerwear',
      sellingPrice: 499.0,
      availableQty: 85,
    },
    {
      skuCode: 'AURORA-SKU-003',
      merchantId: 'aurora',
      itemTitle: '极光经典立体剪裁工装裤 (耐磨抗皱)',
      categoryName: 'pants',
      sellingPrice: 259.0,
      availableQty: 120,
    },
    {
      skuCode: 'AURORA-SKU-004',
      merchantId: 'aurora',
      itemTitle: '极光复古气垫缓震慢跑鞋 (全掌缓震)',
      categoryName: 'shoes',
      sellingPrice: 399.0,
      availableQty: 65,
    },
  ];

  for (const p of products) {
    await pool.query(
      `INSERT INTO third_party_inventory (sku_code, merchant_id, item_title, category_name, selling_price, available_qty, is_on_shelf)
       VALUES ($1, $2, $3, $4, $5, $6, TRUE)
       ON CONFLICT (sku_code) DO UPDATE SET
         selling_price = EXCLUDED.selling_price,
         available_qty = EXCLUDED.available_qty,
         item_title = EXCLUDED.item_title`,
      [p.skuCode, p.merchantId, p.itemTitle, p.categoryName, p.sellingPrice, p.availableQty],
    );
  }

  // 3. 写入测试顾客数据 (Customer)
  const customerAddresses = [
    {
      id: 'ADDR-101',
      recipientName: '张伟',
      phone: '13800138000',
      fullAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
      province: '北京市',
      city: '北京市',
      district: '海淀区',
      isDefault: true,
    },
    {
      id: 'ADDR-102',
      recipientName: '张伟(公司)',
      phone: '13800138000',
      fullAddress: '北京市朝阳区望京SOHO T1座 1508室',
      province: '北京市',
      city: '北京市',
      district: '朝阳区',
      isDefault: false,
    },
  ];

  await pool.query(
    `INSERT INTO third_party_customers (customer_id, merchant_id, external_email, customer_name, phone_number, vip_tier, delivery_addresses)
     VALUES ($1, $2, $3, $4, $5, $6, $7)
     ON CONFLICT (customer_id) DO UPDATE SET
       delivery_addresses = EXCLUDED.delivery_addresses,
       customer_name = EXCLUDED.customer_name`,
    [
      'CUST-8801',
      'aurora',
      'zhangwei@example.com',
      '张伟',
      '13800138000',
      'DIAMOND',
      JSON.stringify(customerAddresses),
    ],
  );

  // 4. 写入真实测试订单 (Orders & Items)
  // 订单 1: 待发货 (可改地址、可退款)
  await pool.query(
    `INSERT INTO third_party_orders (ext_order_sn, merchant_id, customer_id, order_status, pay_amount, recipient_name, recipient_phone, shipping_address, can_modify_address, can_refund)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
     ON CONFLICT (ext_order_sn) DO UPDATE SET
       order_status = EXCLUDED.order_status,
       shipping_address = EXCLUDED.shipping_address,
       can_modify_address = EXCLUDED.can_modify_address`,
    [
      'AURORA-ORD-2026-9081',
      'aurora',
      'CUST-8801',
      'PAID',
      499.0,
      '张伟',
      '13800138000',
      '北京市海淀区中关村南大街1号院8号楼1201室',
      true,
      true,
    ],
  );

  await pool.query(
    `INSERT INTO third_party_order_items (item_id, ext_order_sn, sku_code, item_title, unit_price, buy_qty)
     VALUES ($1, $2, $3, $4, $5, $6)
     ON CONFLICT (item_id) DO NOTHING`,
    ['ITEM-9081-1', 'AURORA-ORD-2026-9081', 'AURORA-SKU-002', '极光轻量三防连帽冲锋衣 (暴雨级防水)', 499.0, 1],
  );

  // 订单 2: 已发货 (包裹已出库，不可改地址，可申请售后)
  await pool.query(
    `INSERT INTO third_party_orders (ext_order_sn, merchant_id, customer_id, order_status, pay_amount, recipient_name, recipient_phone, shipping_address, carrier_code, tracking_no, can_modify_address, can_refund)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
     ON CONFLICT (ext_order_sn) DO UPDATE SET
       order_status = EXCLUDED.order_status,
       tracking_no = EXCLUDED.tracking_no,
       can_modify_address = EXCLUDED.can_modify_address`,
    [
      'AURORA-ORD-2026-9082',
      'aurora',
      'CUST-8801',
      'SHIPPED',
      129.0,
      '张伟',
      '13800138000',
      '北京市海淀区中关村南大街1号院8号楼1201室',
      'SF',
      'SF18928374619',
      false,
      true,
    ],
  );

  await pool.query(
    `INSERT INTO third_party_order_items (item_id, ext_order_sn, sku_code, item_title, unit_price, buy_qty)
     VALUES ($1, $2, $3, $4, $5, $6)
     ON CONFLICT (item_id) DO NOTHING`,
    ['ITEM-9082-1', 'AURORA-ORD-2026-9082', 'AURORA-SKU-001', '极光纯棉重磅短袖T恤 (220g重磅)', 129.0, 1],
  );

  console.log('✅ [SeedMerchant] Third-party merchant database tables & seed data initialized successfully.');
}

if (import.meta.main || process.argv[1]?.endsWith('seedThirdPartyMerchant.ts')) {
  seedThirdPartyMerchant()
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('❌ [SeedMerchant] Failed to seed third-party merchant:', err);
      process.exit(1);
    });
}
