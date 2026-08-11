import { Client } from "pg";

async function main() {
  const dbUrl =
    process.env.DATABASE_URL ||
    "postgres://agent_user:agent_password@localhost:5432/agent_platform";
  console.log(
    "🚀 [PG Seed] 启动 100% 纯血 PostgreSQL 多租户 SaaS 关系型数据物理注入...",
  );
  console.log("[PG Seed] 目标连接 URL:", dbUrl);

  const client = new Client({ connectionString: dbUrl });

  try {
    await client.connect();

    console.log("[PG Seed] 正在清理物理 PostgreSQL 历史表冲突结构...");
    // 清除历史旧结构以防字段/约束冲突导致 Seeding 报错
    await client.query(`
      DROP TABLE IF EXISTS "session_metrics" CASCADE;
      DROP TABLE IF EXISTS "order_items" CASCADE;
      DROP TABLE IF EXISTS "orders" CASCADE;
      DROP TABLE IF EXISTS "products" CASCADE;
      DROP TABLE IF EXISTS "business_configs" CASCADE;
      DROP TABLE IF EXISTS "messages" CASCADE;
      DROP TABLE IF EXISTS "threads" CASCADE;
      DROP TABLE IF EXISTS "users" CASCADE;
    `);

    // 1. 创建基础核心表
    console.log("[PG Seed] 正在重新物理创建多租户 SaaS 精密关系型表结构...");

    await client.query(`
      CREATE TABLE IF NOT EXISTS users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email TEXT UNIQUE,
        created_at TIMESTAMP DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS threads (
        id TEXT PRIMARY KEY,
        user_id UUID REFERENCES users(id),
        business_id TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        thread_id TEXT REFERENCES threads(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        carrier TEXT NOT NULL,
        tracking_number TEXT NOT NULL,
        estimated_delivery TEXT NOT NULL,
        user_id TEXT,
        business_id TEXT NOT NULL,
        total_amount REAL
      );

      CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY,
        business_id TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        price REAL NOT NULL,
        stock INTEGER DEFAULT 99,
        created_at TIMESTAMP DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS order_items (
        id TEXT PRIMARY KEY,
        order_id TEXT REFERENCES orders(order_id) ON DELETE CASCADE,
        product_id TEXT REFERENCES products(id) ON DELETE CASCADE,
        quantity INTEGER NOT NULL,
        price_at_purchase REAL NOT NULL
      );

      CREATE TABLE IF NOT EXISTS business_configs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        business_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        config JSONB NOT NULL,
        is_active BOOLEAN DEFAULT false,
        created_by TEXT,
        created_at TIMESTAMP DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS session_metrics (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        business_id TEXT NOT NULL,
        thread_id TEXT REFERENCES threads(id) ON DELETE CASCADE,
        total_tokens INTEGER DEFAULT 0,
        calculated_cost_usd REAL DEFAULT 0.0,
        node_transitions_count INTEGER DEFAULT 1,
        resolution_status TEXT NOT NULL,
        avg_latency_ms REAL DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
      );
    `);
    console.log("[PG Seed] 表结构创建成功！开始灌入高保真演示业务数据...");

    // 2. 注入 Users & Threads
    const userEmail = "test@example.com";
    const userRes = await client.query(
      "INSERT INTO users (email) VALUES ($1) ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email RETURNING id",
      [userEmail],
    );
    const userId = userRes.rows[0].id;
    console.log(`[PG Seed] ✅ 物理用户注册成功: ${userEmail} (ID: ${userId})`);

    // 注册三个不同商户租户的会话，演示 SaaS 级别完全逻辑物理隔离
    await client.query(`
      INSERT INTO threads (id, user_id, business_id, status)
      VALUES
        ('thread_nike_demo', '${userId}', 'nike', 'active'),
        ('thread_adidas_demo', '${userId}', 'adidas', 'active')
      ON CONFLICT (id) DO NOTHING;
    `);
    console.log("[PG Seed] ✅ 物理多租户 threads 会话注入成功！");

    // 3. 注入 Products 商品数据
    await client.query(`
      INSERT INTO products (id, business_id, name, description, price, stock)
      VALUES
        ('prod_nike_1', 'nike', 'Nike Pegasus Trail 5 越野跑鞋', '专为户外越野打造，搭载高强度 React 缓震泡棉，耐磨抓地橡胶大底。', 139.99, 45),
        ('prod_nike_2', 'nike', 'Nike Element 户外防风连帽衫', '高透气防泼水面料，反光条设计保障夜间户外运动安全。', 85.00, 30),
        ('prod_adidas_1', 'adidas', 'Adidas Ultraboost 1.0 经典跑鞋', '卓越的 Boost 能量回馈中底，Primeknit 贴合针织鞋面。', 179.99, 50),
        ('prod_adidas_2', 'adidas', 'Adidas Multi-Pack 运动专业棉袜 (3双装)', '吸湿排汗，足弓加厚减震缓冲。', 12.50, 120),
        ('prod_eco_1', 'ecommerce', '电商主站极绒亲肤抗静电保暖毯', '高克重复合超细纤维，环保防静电印染，居家车载必备。', 49.99, 85)
      ON CONFLICT (id) DO NOTHING;
    `);
    console.log("[PG Seed] ✅ 物理 products 商品条目注入成功！");

    // 4. 注入 Orders & Order Items
    // 注入4笔极具演示冲突的精妙订单，完美演示小额免签放行 vs 超过时效拦截 vs 大额挂起审核
    await client.query(`
      INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery, user_id, business_id, total_amount)
      VALUES
        -- 1. Nike 标准订单：下单在30天退款期以内，退款金额 $139.99 属于 Nike $150 限额以内。申请退款将【触发限额免签直接放行】！
        ('ORD-98712', 'shipped', 'FedEx', '1234567890', '2026-07-20', '${userId}', 'nike', 139.99),

        -- 2. Adidas 合规小额单：退款金额 $12.50 小于 Adidas $120 门槛且在 14天时效内。申请退款将【自动直接放行】！
        ('ORD-ADIDAS-OK', 'delivered', 'SF Express', 'SF1234567', '2026-07-22', '${userId}', 'adidas', 12.50),

        -- 3. Adidas 逾期单：送达时间为 2026-06-10，已严重跨越 14天退货期规定。申请退款将【触发物理工具时效红线直接拦截拒退】！
        ('ORD-ADIDAS-EXPIRED', 'delivered', 'DHL', 'DHL88712', '2026-06-10', '${userId}', 'adidas', 179.99),

        -- 4. 电商主站大额单：送达在 7天时效内，但金额 $199.96 大于主站 $100 自动免签线。申请退款将【触发安全拦截，自动生成橙色 HITL 待审批卡片】！
        ('ORD-ECO-LARGE', 'delivered', 'FedEx', 'FEDEX3332', '2026-07-23', '${userId}', 'ecommerce', 199.96)
      ON CONFLICT (order_id) DO NOTHING;
    `);

    await client.query(`
      INSERT INTO order_items (id, order_id, product_id, quantity, price_at_purchase)
      VALUES
        ('item_nike_1', 'ORD-98712', 'prod_nike_1', 1, 139.99),
        ('item_adidas_ok_1', 'ORD-ADIDAS-OK', 'prod_adidas_2', 1, 12.50),
        ('item_adidas_exp_1', 'ORD-ADIDAS-EXPIRED', 'prod_adidas_1', 1, 179.99),
        ('item_eco_large_1', 'ORD-ECO-LARGE', 'prod_eco_1', 4, 49.99)
      ON CONFLICT (id) DO NOTHING;
    `);
    console.log(
      "[PG Seed] ✅ 物理 orders 及关系型 order_items 明细明细树注入成功！",
    );

    // 5. 注入 SaaS 商户活跃热加载配置规则快照 (Business Configs)
    await client.query(`
      INSERT INTO business_configs (business_id, version, config, is_active, created_by)
      VALUES
        ('ecommerce', 1, '{"systemPrompt": "You are a professional customer assistant. Autopilot refund limit is $100.", "refundAutoApprovalLimit": 100}', true, 'admin'),
        ('nike', 1, '{"systemPrompt": "You are a friendly Nike representative. Run like the wind! Autopilot refund limit is $150.", "refundAutoApprovalLimit": 150}', true, 'admin'),
        ('adidas', 1, '{"systemPrompt": "You are an energetic Adidas assistant. Impossible is nothing! Autopilot refund limit is $120.", "refundAutoApprovalLimit": 120}', true, 'admin')
      ON CONFLICT (id) DO NOTHING;
    `);
    console.log("[PG Seed] ✅ 物理 SaaS 商户热加载配置快照注入成功！");

    // 6. 注入会话度量历史数据，使后台 Analytics BI 面板瞬间具备精美的统计走势！
    await client.query(`
      INSERT INTO session_metrics (business_id, thread_id, total_tokens, calculated_cost_usd, node_transitions_count, resolution_status, avg_latency_ms, created_at)
      VALUES
        ('nike', 'thread_nike_demo', 4500, 0.000675, 4, 'resolved_auto', 2800, NOW() - INTERVAL '1 hour'),
        ('nike', 'thread_nike_demo', 12500, 0.001875, 7, 'waiting_approval', 5200, NOW() - INTERVAL '3 hours'),
        ('nike', 'thread_nike_demo', 3800, 0.000570, 3, 'resolved_auto', 2100, NOW() - INTERVAL '5 hours'),
        ('nike', 'thread_nike_demo', 9200, 0.001380, 5, 'rejected', 4100, NOW() - INTERVAL '8 hours'),
        ('nike', 'thread_nike_demo', 5100, 0.000765, 4, 'cancelled', 3100, NOW() - INTERVAL '12 hours'),
        ('nike', 'thread_nike_demo', 6200, 0.000930, 5, 'resolved_auto', 3200, NOW() - INTERVAL '30 minutes'),
        ('nike', 'thread_nike_demo', 14200, 0.002130, 8, 'waiting_approval', 6100, NOW() - INTERVAL '2 hours'),
        ('adidas', 'thread_adidas_demo', 3100, 0.000465, 3, 'resolved_auto', 1800, NOW() - INTERVAL '15 minutes')
      ON CONFLICT (id) DO NOTHING;
    `);
    console.log("[PG Seed] ✅ 物理历史 session_metrics BI 度量数据成功注入！");

    console.log(
      "\n🌟 =================================================================",
    );
    console.log(
      "✅ [PG Seed] PostgreSQL 物理多租户多商户种子数据注入大圆满完成！",
    );
    console.log(
      "🌟 =================================================================\n",
    );

    await client.end();
  } catch (err: unknown) {
    const errorMessage = err instanceof Error ? err.message : String(err);
    console.error("❌ [PG Seed] PostgreSQL Seeding 失败:", errorMessage);
    try {
      await client.end();
    } catch {}
  }
}

main();
