import { ensureMerchantDatabaseAndTables, getMerchantPgPool } from './merchantDb';

export async function seedMerchantData(): Promise<void> {
  await ensureMerchantDatabaseAndTables();
  const pool = getMerchantPgPool();

  console.log('🌱 [Merchant DB] 开始执行独立商户多规格领域数据 Seed 初始化...');

  // 清理现有商户数据保证幂等
  await pool.query(`
    DELETE FROM merchant_order_items;
    DELETE FROM merchant_audit_logs;
    DELETE FROM merchant_orders;
    DELETE FROM merchant_customers;
    DELETE FROM merchant_skus;
    DELETE FROM merchant_spus;
  `);

  // 1. 插入 SPU 实体
  // SPU 1: 三合一硬壳冲锋衣 (极光潮品)
  const spu1Res = await pool.query(
    `
    INSERT INTO merchant_spus (
      spu_code, title, subtitle, description, category, brand, main_image, banner_images, spec_dimensions, specs, status
    ) VALUES (
      $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
    ) RETURNING id;
  `,
    [
      'SPU-AURORA-001',
      '极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)',
      '暴雨级防水 | GORE-TEX 3L级面料 | 智能温控锁温',
      '专为高海拔严苛户外探险打造，采用全压胶三层复合微孔纳米膜，抗暴风雨兼顾极高透气性。配有 YKK 双向防水拉链、立体可调节防风帽及雪裙系统。',
      '户外机能',
      'AURORA 极光',
      'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=800&auto=format&fit=crop&q=60',
      JSON.stringify([
        'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=800&auto=format&fit=crop&q=60',
        'https://images.unsplash.com/photo-1544441893-675973e31985?w=800&auto=format&fit=crop&q=60',
      ]),
      JSON.stringify([
        { name: '颜色', values: ['曜石黑', '极夜绿', '雪山白'] },
        {
          name: '尺码',
          values: ['M (170/88A)', 'L (175/92A)', 'XL (180/96A)'],
        },
      ]),
      JSON.stringify({
        面料材质: '100% 聚酰胺纤维 + 3L微孔复合膜',
        防水指数: '20000mmH2O (暴雨级)',
        透气指数: '15000g/m²/24h',
        拉链品牌: 'YKK 双向全防水压胶拉链',
        适用季节: '秋冬/四季通用',
        版型: '3D立体剪裁',
      }),
      'ON_SALE',
    ],
  );
  const spu1Id = spu1Res.rows[0].id;

  // 插入 SPU 1 的多颜色、多尺码 SKU 矩阵
  const spu1Skus = [
    {
      code: 'AURORA-SKU-001-BLK-M',
      title: '极光三合一冲锋衣 曜石黑 M码',
      attrs: { 颜色: '曜石黑', 尺码: 'M (170/88A)' },
      price: 1299.0,
      originalPrice: 1599.0,
      stock: 45,
      barcode: '690123400101',
    },
    {
      code: 'AURORA-SKU-002',
      title: '极光三合一冲锋衣 曜石黑 L码 (旗舰主推)',
      attrs: { 颜色: '曜石黑', 尺码: 'L (175/92A)' },
      price: 1299.0,
      originalPrice: 1599.0,
      stock: 60,
      barcode: '690123400102',
    },
    {
      code: 'AURORA-SKU-001-BLK-XL',
      title: '极光三合一冲锋衣 曜石黑 XL码',
      attrs: { 颜色: '曜石黑', 尺码: 'XL (180/96A)' },
      price: 1299.0,
      originalPrice: 1599.0,
      stock: 30,
      barcode: '690123400103',
    },
    {
      code: 'AURORA-SKU-001-GRN-M',
      title: '极光三合一冲锋衣 极夜绿 M码',
      attrs: { 颜色: '极夜绿', 尺码: 'M (170/88A)' },
      price: 1299.0,
      originalPrice: 1599.0,
      stock: 25,
      barcode: '690123400104',
    },
    {
      code: 'AURORA-SKU-001-GRN-L',
      title: '极光三合一冲锋衣 极夜绿 L码',
      attrs: { 颜色: '极夜绿', 尺码: 'L (175/92A)' },
      price: 1299.0,
      originalPrice: 1599.0,
      stock: 38,
      barcode: '690123400105',
    },
    {
      code: 'AURORA-SKU-001-WHT-L',
      title: '极光三合一冲锋衣 雪山白 L码',
      attrs: { 颜色: '雪山白', 尺码: 'L (175/92A)' },
      price: 1349.0,
      originalPrice: 1699.0,
      stock: 15,
      barcode: '690123400106',
    },
  ];

  for (const sku of spu1Skus) {
    await pool.query(
      `
      INSERT INTO merchant_skus (
        spu_id, sku_code, sku_title, spec_attributes, price, original_price, stock, barcode, image_url
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
    `,
      [
        spu1Id,
        sku.code,
        sku.title,
        JSON.stringify(sku.attrs),
        sku.price,
        sku.originalPrice,
        sku.stock,
        sku.barcode,
        'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=800&auto=format&fit=crop&q=60',
      ],
    );
  }

  // SPU 2: 重磅纯棉复古印花短袖T恤
  const spu2Res = await pool.query(
    `
    INSERT INTO merchant_spus (
      spu_code, title, subtitle, description, category, brand, main_image, banner_images, spec_dimensions, specs, status
    ) VALUES (
      $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
    ) RETURNING id;
  `,
    [
      'SPU-AURORA-002',
      '极光2026春夏款 320g重磅精梳纯棉复古印花短袖T恤',
      '高支高密 | 领口防变形织带 | 环保活性印花',
      '采用320克双纱精梳纯棉面料，挺括有型不透肉。领口加固高弹罗纹与双针通肩压条，多次洗涤依旧平整不垮领。',
      '潮流T恤',
      'AURORA 极光',
      'https://images.unsplash.com/photo-1521572267360-ee0c2909d518?w=800&auto=format&fit=crop&q=60',
      JSON.stringify(['https://images.unsplash.com/photo-1521572267360-ee0c2909d518?w=800&auto=format&fit=crop&q=60']),
      JSON.stringify([
        { name: '颜色', values: ['水洗灰', '纯净白', '暗夜黑'] },
        { name: '尺码', values: ['S', 'M', 'L', 'XL'] },
      ]),
      JSON.stringify({
        面料材质: '100% 精梳棉 (320g 重磅双纱)',
        工艺: '水洗做旧 + 环保活性数码喷绘',
        版型: '宽松落肩 Loose Fit',
        领口设计: '加厚高弹罗纹 + 通肩防变形嵌条',
        安全类别: 'GB 18401-2010 B类 (直接接触皮肤)',
      }),
      'ON_SALE',
    ],
  );
  const spu2Id = spu2Res.rows[0].id;

  const spu2Skus = [
    {
      code: 'AURORA-SKU-002-GRY-M',
      title: '重磅纯棉复古T恤 水洗灰 M码',
      attrs: { 颜色: '水洗灰', 尺码: 'M' },
      price: 269.0,
      originalPrice: 329.0,
      stock: 120,
    },
    {
      code: 'AURORA-SKU-002-GRY-L',
      title: '重磅纯棉复古T恤 水洗灰 L码',
      attrs: { 颜色: '水洗灰', 尺码: 'L' },
      price: 269.0,
      originalPrice: 329.0,
      stock: 95,
    },
    {
      code: 'AURORA-SKU-002-WHT-L',
      title: '重磅纯棉复古T恤 纯净白 L码',
      attrs: { 颜色: '纯净白', 尺码: 'L' },
      price: 269.0,
      originalPrice: 329.0,
      stock: 80,
    },
    {
      code: 'AURORA-SKU-002-BLK-XL',
      title: '重磅纯棉复古T恤 暗夜黑 XL码',
      attrs: { 颜色: '暗夜黑', 尺码: 'XL' },
      price: 269.0,
      originalPrice: 329.0,
      stock: 50,
    },
  ];

  for (const sku of spu2Skus) {
    await pool.query(
      `
      INSERT INTO merchant_skus (
        spu_id, sku_code, sku_title, spec_attributes, price, original_price, stock, image_url
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
    `,
      [
        spu2Id,
        sku.code,
        sku.title,
        JSON.stringify(sku.attrs),
        sku.price,
        sku.originalPrice,
        sku.stock,
        'https://images.unsplash.com/photo-1521572267360-ee0c2909d518?w=800&auto=format&fit=crop&q=60',
      ],
    );
  }

  // SPU 3: 考杜拉机能工装裤
  const spu3Res = await pool.query(
    `
    INSERT INTO merchant_spus (
      spu_code, title, subtitle, description, category, brand, main_image, banner_images, spec_dimensions, specs, status
    ) VALUES (
      $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
    ) RETURNING id;
  `,
    [
      'SPU-AURORA-003',
      '极光 Cordura考杜拉耐磨多袋机能工装裤',
      '防泼水特氟龙涂层 | 8口袋收纳系统 | 磁吸战术扣件',
      '精选 Cordura 500D 强韧耐磨面料，搭载 Teflon 纳米抗污防泼水涂层，内置模块化快拆腰带与多层立体风琴口袋。',
      '下装裤类',
      'AURORA 极光',
      'https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=800&auto=format&fit=crop&q=60',
      JSON.stringify(['https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=800&auto=format&fit=crop&q=60']),
      JSON.stringify([
        { name: '颜色', values: ['战术黑', '荒漠卡其', '橄榄绿'] },
        { name: '尺码', values: ['M (30腰)', 'L (32腰)', 'XL (34腰)'] },
      ]),
      JSON.stringify({
        面料材质: 'Cordura 500D 尼龙 + 特氟龙(Teflon)防泼水图层',
        口袋数量: '8个立体多功能风琴袋 + 隐藏拉链仓',
        腰带系统: 'Fidlock 德国磁吸快拆扣',
        耐磨等级: '工业级抗撕裂',
      }),
      'ON_SALE',
    ],
  );
  const spu3Id = spu3Res.rows[0].id;

  const spu3Skus = [
    {
      code: 'AURORA-SKU-003-BLK-M',
      title: 'Cordura机能工装裤 战术黑 M码',
      attrs: { 颜色: '战术黑', 尺码: 'M (30腰)' },
      price: 589.0,
      originalPrice: 799.0,
      stock: 40,
    },
    {
      code: 'AURORA-SKU-003-BLK-L',
      title: 'Cordura机能工装裤 战术黑 L码',
      attrs: { 颜色: '战术黑', 尺码: 'L (32腰)' },
      price: 589.0,
      originalPrice: 799.0,
      stock: 55,
    },
    {
      code: 'AURORA-SKU-003-KHK-L',
      title: 'Cordura机能工装裤 荒漠卡其 L码',
      attrs: { 颜色: '荒漠卡其', 尺码: 'L (32腰)' },
      price: 589.0,
      originalPrice: 799.0,
      stock: 35,
    },
  ];

  for (const sku of spu3Skus) {
    await pool.query(
      `
      INSERT INTO merchant_skus (
        spu_id, sku_code, sku_title, spec_attributes, price, original_price, stock, image_url
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
    `,
      [
        spu3Id,
        sku.code,
        sku.title,
        JSON.stringify(sku.attrs),
        sku.price,
        sku.originalPrice,
        sku.stock,
        'https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=800&auto=format&fit=crop&q=60',
      ],
    );
  }

  // SPU 4: Vibram底复古解构老爹鞋
  const spu4Res = await pool.query(
    `
    INSERT INTO merchant_spus (
      spu_code, title, subtitle, description, category, brand, main_image, banner_images, spec_dimensions, specs, status
    ) VALUES (
      $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11
    ) RETURNING id;
  `,
    [
      'SPU-AURORA-004',
      '极光 Vibram黄金大底 复古解构运动老爹鞋',
      'Vibram防滑湿地大底 | OrthoLite透气鞋垫 | 头层牛反绒拼接',
      '解构美学设计，鞋面融合头层反绒皮与防刮尼龙网布。搭载意大利 Vibram Megagrip 顶级湿地防滑橡胶大底与高弹 EVA 缓震中底。',
      '潮流鞋靴',
      'AURORA 极光',
      'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800&auto=format&fit=crop&q=60',
      JSON.stringify(['https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800&auto=format&fit=crop&q=60']),
      JSON.stringify([
        { name: '颜色', values: ['水泥灰/荧光绿', '复古白/深海蓝'] },
        {
          name: '尺码',
          values: ['40码 (250mm)', '41码 (255mm)', '42码 (260mm)', '43码 (265mm)'],
        },
      ]),
      JSON.stringify({
        鞋面材质: '头层牛反绒皮革 + 高透气 Cordura 网布',
        大底材质: '意大利 Vibram® Megagrip 止滑大底',
        中底配置: '高回弹 超临界发泡 EVA 减震材料',
        鞋垫: 'OrthoLite® 抑菌排汗鞋垫',
      }),
      'ON_SALE',
    ],
  );
  const spu4Id = spu4Res.rows[0].id;

  const spu4Skus = [
    {
      code: 'AURORA-SKU-004-GRY-41',
      title: 'Vibram复古老爹鞋 水泥灰 41码',
      attrs: { 颜色: '水泥灰/荧光绿', 尺码: '41码 (255mm)' },
      price: 899.0,
      originalPrice: 1099.0,
      stock: 20,
    },
    {
      code: 'AURORA-SKU-004-GRY-42',
      title: 'Vibram复古老爹鞋 水泥灰 42码',
      attrs: { 颜色: '水泥灰/荧光绿', 尺码: '42码 (260mm)' },
      price: 899.0,
      originalPrice: 1099.0,
      stock: 28,
    },
    {
      code: 'AURORA-SKU-004-WHT-42',
      title: 'Vibram复古老爹鞋 复古白 42码',
      attrs: { 颜色: '复古白/深海蓝', 尺码: '42码 (260mm)' },
      price: 899.0,
      originalPrice: 1099.0,
      stock: 18,
    },
  ];

  for (const sku of spu4Skus) {
    await pool.query(
      `
      INSERT INTO merchant_skus (
        spu_id, sku_code, sku_title, spec_attributes, price, original_price, stock, image_url
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
    `,
      [
        spu4Id,
        sku.code,
        sku.title,
        JSON.stringify(sku.attrs),
        sku.price,
        sku.originalPrice,
        sku.stock,
        'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800&auto=format&fit=crop&q=60',
      ],
    );
  }

  // 2. 插入顾客档案
  await pool.query(
    `
    INSERT INTO merchant_customers (
      customer_id, name, phone, email, member_level, addresses, tags
    ) VALUES ($1, $2, $3, $4, $5, $6, $7);
  `,
    [
      'CUST-8801',
      '张伟',
      '13800138000',
      'zhangwei@example.com',
      '黑金SVIP',
      JSON.stringify([
        {
          id: 'addr_01',
          recipientName: '张伟',
          phone: '13800138000',
          fullAddress: '北京市朝阳区建国门外大街1号国贸大厦A座 3801室',
          isDefault: true,
        },
        {
          id: 'addr_02',
          recipientName: '张伟',
          phone: '13800138000',
          fullAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
          isDefault: false,
        },
      ]),
      JSON.stringify(['高净值客户', '户外发烧友', '偏好曜石黑配色']),
    ],
  );

  // 3. 插入初始订单与明细
  // 订单 1: 待发货订单 (AURORA-ORD-2026-9081)
  await pool.query(
    `
    INSERT INTO merchant_orders (
      order_id, customer_id, status, total_amount, currency, shipping_address, tracking_info, is_returnable, is_address_modifiable
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
  `,
    [
      'AURORA-ORD-2026-9081',
      'CUST-8801',
      'PAID',
      1299.0,
      'CNY',
      JSON.stringify({
        recipientName: '张伟',
        phone: '13800138000',
        fullAddress: '北京市朝阳区建国门外大街1号国贸大厦A座 3801室',
      }),
      null,
      true,
      true,
    ],
  );

  await pool.query(
    `
    INSERT INTO merchant_order_items (
      order_id, spu_id, sku_code, title, sku_title, quantity, price, image_url, spec_summary
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
  `,
    [
      'AURORA-ORD-2026-9081',
      'SPU-AURORA-001',
      'AURORA-SKU-002',
      '极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)',
      '极光三合一冲锋衣 曜石黑 L码 (旗舰主推)',
      1,
      1299.0,
      'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=800&auto=format&fit=crop&q=60',
      '曜石黑 / L (175/92A)',
    ],
  );

  // 订单 2: 已发货订单 (AURORA-ORD-2026-9082)
  await pool.query(
    `
    INSERT INTO merchant_orders (
      order_id, customer_id, status, total_amount, currency, shipping_address, tracking_info, is_returnable, is_address_modifiable
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
  `,
    [
      'AURORA-ORD-2026-9082',
      'CUST-8801',
      'SHIPPED',
      589.0,
      'CNY',
      JSON.stringify({
        recipientName: '张伟',
        phone: '13800138000',
        fullAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
      }),
      JSON.stringify({
        carrier: 'SF',
        trackingNumber: 'SF10829384729',
        status: 'IN_TRANSIT',
        latestLocation: '北京顺丰分拨中心',
      }),
      true,
      false, // 已发货禁止修改地址
    ],
  );

  await pool.query(
    `
    INSERT INTO merchant_order_items (
      order_id, spu_id, sku_code, title, sku_title, quantity, price, image_url, spec_summary
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9);
  `,
    [
      'AURORA-ORD-2026-9082',
      'SPU-AURORA-003',
      'AURORA-SKU-003-BLK-L',
      '极光 Cordura考杜拉耐磨多袋机能工装裤',
      'Cordura机能工装裤 战术黑 L码',
      1,
      589.0,
      'https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=800&auto=format&fit=crop&q=60',
      '战术黑 / L (32腰)',
    ],
  );

  console.log('✅ [Merchant DB] 独立物理数据库 SPU/SKU/Specs 多规格数据初始化完成！');
}

if (import.meta.main) {
  seedMerchantData()
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('❌ Seed Failed:', err);
      process.exit(1);
    });
}
