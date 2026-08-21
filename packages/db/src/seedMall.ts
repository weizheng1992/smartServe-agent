import { eq } from 'drizzle-orm';
import { getDrizzle } from './client';
import { orderItems, orders, products, users } from './schema';

export async function seedMallData() {
  console.log('🌱 [Seed Mall Data] 开始初始化商场全量商品库、运营经理归属与订单销售记录...');

  const drizzle = getDrizzle();

  // 1. 创建或获取默认运营经理用户
  const defaultManagerEmail = 'weizheng1004@qq.com';
  let managerId = '83d67d4e-104c-4325-8aa7-10d4389fc725';

  try {
    const existingUsers = await drizzle.select().from(users).where(eq(users.email, defaultManagerEmail)).limit(1);

    if (existingUsers.length > 0) {
      managerId = existingUsers[0].id;
      console.log(`[Seed Mall Data] 绑定现有运营经理: ${defaultManagerEmail} (ID: ${managerId})`);
    } else {
      const inserted = await drizzle
        .insert(users)
        .values({
          email: defaultManagerEmail,
        })
        .returning();
      managerId = inserted[0].id;
      console.log(`[Seed Mall Data] 创建新运营经理: ${defaultManagerEmail} (ID: ${managerId})`);
    }
  } catch (err) {
    console.warn('[Seed Mall Data] 用户获取降级为固定 UUID:', err);
  }

  // 2. 准备丰富的商场商品数据 (覆盖高销量、高GMV、高利润不同特征)
  const mallProducts = [
    {
      id: 'prod_nike_vaporfly',
      businessId: 'nike',
      managerId, // 由当前用户负责
      name: 'Nike ZoomX Vaporfly 3 顶级竞速跑鞋',
      category: 'shoes',
      description: '碳纤维全掌铲型推进板，马拉松专业竞速神器',
      price: 1599.0, // 售价
      costPrice: 499.0, // 成本 -> 单件毛利 1100 元 (高毛利冠军)
      stock: 50,
    },
    {
      id: 'prod_nike_pegasus',
      businessId: 'nike',
      managerId, // 由当前用户负责
      name: 'Nike Air Zoom Pegasus 40 经典日常飞马跑鞋',
      category: 'shoes',
      description: '全天候透气缓震，国民级日常跑步训练鞋',
      price: 899.0, // 售价
      costPrice: 350.0, // 成本 -> 单件毛利 549 元 (高GMV冠军)
      stock: 200,
    },
    {
      id: 'prod_nike_socks_pack',
      businessId: 'nike',
      managerId, // 由当前用户负责
      name: 'Nike Everyday Plus 缓震运动长筒袜 (3双装)',
      category: 'accessories',
      description: 'Dri-FIT 速干排汗科技，足弓支撑防滑',
      price: 99.0, // 售价
      costPrice: 20.0, // 成本 -> 单件毛利 79 元 (出货销量 Volume 冠军)
      stock: 1000,
    },
    {
      id: 'prod_nike_tech_fleece',
      businessId: 'nike',
      managerId, // 由当前用户负责
      name: 'Nike Sportswear Tech Fleece 运动立领连帽衫',
      category: 'apparel',
      description: '轻盈双面针织保暖结构，时尚保暖机能剪裁',
      price: 799.0,
      costPrice: 280.0,
      stock: 80,
    },
    {
      id: 'prod_nike_wristband',
      businessId: 'nike',
      managerId: 'other_manager_alex', // 其他人负责的商品 (用于测试数据权限隔离)
      name: 'Nike Dri-FIT 经典运动吸汗护腕',
      category: 'accessories',
      description: '高弹吸水毛圈面料',
      price: 49.0,
      costPrice: 10.0,
      stock: 300,
    },
    {
      id: 'prod_adidas_ultraboost',
      businessId: 'adidas', // Adidas 租户隔离商品
      managerId,
      name: 'Adidas Ultraboost Light 旗舰轻量爆米花跑鞋',
      category: 'shoes',
      description: 'Light BOOST 材质缓震回弹',
      price: 1399.0,
      costPrice: 450.0,
      stock: 60,
    },
  ];

  for (const p of mallProducts) {
    await drizzle
      .insert(products)
      .values(p)
      .onConflictDoUpdate({
        target: products.id,
        set: {
          name: p.name,
          businessId: p.businessId,
          managerId: p.managerId,
          category: p.category,
          description: p.description,
          price: p.price,
          costPrice: p.costPrice,
          stock: p.stock,
        },
      });
  }
  console.log(`[Seed Mall Data] 成功同步 ${mallProducts.length} 款物理商品！`);

  // 3. 构造历史交易订单与订单项明细 (模拟真实销量与流水)
  const seedOrders = [
    {
      orderId: 'ORD-MALL-001',
      businessId: 'nike',
      userId: managerId,
      status: 'delivered',
      carrier: 'SF Express',
      trackingNumber: 'SF9900112233',
      estimatedDelivery: '2026-08-15',
      totalAmount: 14850.0,
      items: [
        {
          productId: 'prod_nike_socks_pack',
          quantity: 150,
          priceAtPurchase: 99.0,
          costAtPurchase: 20.0,
        },
      ],
    },
    {
      orderId: 'ORD-MALL-002',
      businessId: 'nike',
      userId: managerId,
      status: 'delivered',
      carrier: 'JD Logistics',
      trackingNumber: 'JD7788990011',
      estimatedDelivery: '2026-08-16',
      totalAmount: 26970.0,
      items: [
        {
          productId: 'prod_nike_pegasus',
          quantity: 30,
          priceAtPurchase: 899.0,
          costAtPurchase: 350.0,
        },
      ],
    },
    {
      orderId: 'ORD-MALL-003',
      businessId: 'nike',
      userId: managerId,
      status: 'delivered',
      carrier: 'SF Express',
      trackingNumber: 'SF6655443322',
      estimatedDelivery: '2026-08-17',
      totalAmount: 28782.0,
      items: [
        {
          productId: 'prod_nike_vaporfly',
          quantity: 18,
          priceAtPurchase: 1599.0,
          costAtPurchase: 499.0,
        },
      ],
    },
    {
      orderId: 'ORD-MALL-004',
      businessId: 'nike',
      userId: managerId,
      status: 'shipped',
      carrier: 'ZTO Express',
      trackingNumber: 'ZTO11223344',
      estimatedDelivery: '2026-08-22',
      totalAmount: 7990.0,
      items: [
        {
          productId: 'prod_nike_tech_fleece',
          quantity: 10,
          priceAtPurchase: 799.0,
          costAtPurchase: 280.0,
        },
      ],
    },
  ];

  for (const o of seedOrders) {
    await drizzle
      .insert(orders)
      .values({
        orderId: o.orderId,
        businessId: o.businessId,
        userId: o.userId,
        status: o.status,
        carrier: o.carrier,
        trackingNumber: o.trackingNumber,
        estimatedDelivery: o.estimatedDelivery,
        totalAmount: o.totalAmount,
      })
      .onConflictDoUpdate({
        target: orders.orderId,
        set: {
          status: o.status,
          totalAmount: o.totalAmount,
        },
      });

    for (let i = 0; i < o.items.length; i++) {
      const itm = o.items[i];
      const itemId = `item_${o.orderId}_${i + 1}`;
      await drizzle
        .insert(orderItems)
        .values({
          id: itemId,
          orderId: o.orderId,
          productId: itm.productId,
          quantity: itm.quantity,
          priceAtPurchase: itm.priceAtPurchase,
          costAtPurchase: itm.costAtPurchase,
        })
        .onConflictDoUpdate({
          target: orderItems.id,
          set: {
            quantity: itm.quantity,
            priceAtPurchase: itm.priceAtPurchase,
            costAtPurchase: itm.costAtPurchase,
          },
        });
    }
  }

  console.log('✅ [Seed Mall Data] 商场全量数据与销售明细初始化完成！');
}

if (import.meta.main) {
  seedMallData().catch((err) => {
    console.error('❌ [Seed Mall Data] Failed:', err);
  });
}
