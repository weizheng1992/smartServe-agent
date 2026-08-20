import { db } from "../packages/db/src";
import { OrderDomainService } from "../packages/tools/src/orderDomainService";

async function main() {
  const targetEmail = "weizheng1004@qq.com";
  console.log(`[Seed Orders] 正在查找或创建用户: ${targetEmail}`);

  // 1. 获取或创建目标用户
  const user = await db.findOrCreateUserByEmail(targetEmail);
  console.log(
    `[Seed Orders] 用户已就绪: ID = ${user.id}, Email = ${user.email}`,
  );

  // 2. 为该用户创建不同商户的测试会话 (Thread)
  const merchants = [
    {
      businessId: "ecommerce",
      name: "电商通用商城",
      orders: [
        {
          orderId: "ORD-ECOM-889901",
          status: "shipped",
          carrier: "SF Express (顺丰速运)",
          trackingNumber: "SF1092837465",
          estimatedDelivery: "2026-08-25",
          totalAmount: 299.0,
          items: [
            {
              productId: "prod_ecom_wireless_headphone",
              name: "无线降噪头戴耳机",
              quantity: 1,
              price: 299.0,
            },
          ],
        },
        {
          orderId: "ORD-ECOM-889902",
          status: "delivered",
          carrier: "JD Logistics (京东物流)",
          trackingNumber: "JD8847291038",
          estimatedDelivery: "2026-08-18",
          totalAmount: 158.0,
          items: [
            {
              productId: "prod_ecom_smart_cup",
              name: "恒温暖暖杯礼盒",
              quantity: 2,
              price: 79.0,
            },
          ],
        },
      ],
    },
    {
      businessId: "nike",
      name: "Nike 官方专营店",
      orders: [
        {
          orderId: "ORD-NIKE-772201",
          status: "shipped",
          carrier: "SF Express (顺丰速运)",
          trackingNumber: "SF9938271625",
          estimatedDelivery: "2026-08-23",
          totalAmount: 1299.0,
          items: [
            {
              productId: "prod_nike_air_jordan_1",
              name: "Air Jordan 1 Retro High OG (42.5码)",
              quantity: 1,
              price: 1299.0,
            },
          ],
        },
        {
          orderId: "ORD-NIKE-772202",
          status: "delivered",
          carrier: "EMS 特快专递",
          trackingNumber: "EMS4433221100",
          estimatedDelivery: "2026-08-12",
          totalAmount: 499.0,
          items: [
            {
              productId: "prod_nike_dri_fit_hoodie",
              name: "Dri-FIT 运动训练连帽卫衣 (L码/黑色)",
              quantity: 1,
              price: 499.0,
            },
          ],
        },
      ],
    },
    {
      businessId: "adidas",
      name: "Adidas 官方旗舰店",
      orders: [
        {
          orderId: "ORD-ADIDAS-663301",
          status: "shipped",
          carrier: "ZTO Express (中通快递)",
          trackingNumber: "ZT7788990011",
          estimatedDelivery: "2026-08-24",
          totalAmount: 899.0,
          items: [
            {
              productId: "prod_adidas_ultraboost_light",
              name: "Ultraboost Light 跑鞋 (42码/云白)",
              quantity: 1,
              price: 899.0,
            },
          ],
        },
        {
          orderId: "ORD-ADIDAS-663302",
          status: "processing",
          carrier: "YTO Express (圆通速递)",
          trackingNumber: "YT1234567890",
          estimatedDelivery: "2026-08-26",
          totalAmount: 349.0,
          items: [
            {
              productId: "prod_adidas_originals_backpack",
              name: "Originals 经典三叶草双肩背包",
              quantity: 1,
              price: 349.0,
            },
          ],
        },
      ],
    },
  ];

  for (const merchant of merchants) {
    console.log(
      `\n📦 开始为商户【${merchant.name} (${merchant.businessId})】注入商品与订单...`,
    );

    // 确保该商户下有对应的激活会话
    const threadId = `thread_${merchant.businessId}_${user.id.slice(0, 8)}`;
    await db.createThread(threadId, user.id, merchant.businessId);
    console.log(`  ✓ 绑定/检查会话: threadId = ${threadId}`);

    for (const ord of merchant.orders) {
      // 1. 确保商品存在
      for (const it of ord.items) {
        await db.execute(
          `INSERT INTO products (id, business_id, name, description, price, stock)
           VALUES ($1, $2, $3, $4, $5, 99)
           ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, price = EXCLUDED.price`,
          [
            it.productId,
            merchant.businessId,
            it.name,
            `${merchant.name} - ${it.name}`,
            it.price,
          ],
        );
      }

      // 2. 调用 OrderDomainService.createOrder 创建订单与明细
      const createRes = await OrderDomainService.createOrder({
        orderId: ord.orderId,
        userId: user.id,
        businessId: merchant.businessId,
        carrier: ord.carrier,
        trackingNumber: ord.trackingNumber,
        estimatedDelivery: ord.estimatedDelivery,
        totalAmount: ord.totalAmount,
        items: ord.items.map((it) => ({
          productId: it.productId,
          quantity: it.quantity,
          priceAtPurchase: it.price,
        })),
      });

      // 调整实际状态 (如 delivered / processing)
      if (ord.status !== "shipped") {
        await db.execute(`UPDATE orders SET status = $1 WHERE order_id = $2`, [
          ord.status,
          ord.orderId,
        ]);
      }

      console.log(
        `  ✓ 成功创建订单: ${ord.orderId} [${ord.status}] 金额: ¥${ord.totalAmount} (商户: ${merchant.businessId})`,
      );
    }

    // 验证该会话下的 listUserOrders 能否查出
    const listRes = await OrderDomainService.listUserOrders(threadId);
    console.log(
      `  🔍 验证该商户会话查单结果: 共查出 ${listRes.orders?.length || 0} 笔订单`,
    );
  }

  console.log(
    `\n🎉 [Seed Orders] 用户 ${targetEmail} 的所有商户订单已全部成功注入真实 PostgreSQL！`,
  );
  process.exit(0);
}

main().catch((err) => {
  console.error("❌ 执行失败:", err);
  process.exit(1);
});
