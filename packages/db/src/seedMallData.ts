import { getPgPool } from './client';

export async function seedMallData() {
  const pool = getPgPool();
  console.log('[DB Seed] 正在向数据库植入商城高保真实体测试数据...');

  // 1. 用户地址种子
  await pool.query(`
    INSERT INTO user_addresses (
      business_id, user_id, receiver_name, receiver_phone,
      province, city, district, detail_address, full_address, tag, is_default, created_at, updated_at
    ) VALUES
      ('ecommerce', 'user_test_001', '张三', '13812345678', '北京市', '北京市', '海淀区', '中关村南大街1号院3号楼802室', '北京市海淀区中关村南大街1号院3号楼802室', 'home', true, NOW(), NOW()),
      ('ecommerce', 'user_test_001', '张三(公司)', '13812345678', '北京市', '北京市', '朝阳区', '酒仙桥路恒通商务园B8栋5层', '北京市朝阳区酒仙桥路恒通商务园B8栋5层', 'company', false, NOW(), NOW()),
      ('nike', 'user_test_001', '张三', '13812345678', '上海市', '上海市', '浦东新区', '陆家嘴环路1000号恒生银行大厦', '上海市浦东新区陆家嘴环路1000号恒生银行大厦', 'company', true, NOW(), NOW())
    ON CONFLICT DO NOTHING;
  `);

  // 2. 确保商品存在
  await pool.query(`
    INSERT INTO products (id, business_id, manager_id, name, category, description, price, cost_price, stock)
    VALUES
      ('prod_nike_air_jordan_1', 'nike', 'mgr_shoes_01', 'Air Jordan 1 Retro High OG', 'shoes', '经典高帮篮球文化鞋', 1299.0, 450.0, 50),
      ('prod_nike_pegasus_40', 'nike', 'mgr_shoes_01', 'Nike Pegasus 40 飞马透气跑鞋', 'shoes', '全掌Zoom Air气垫缓震跑鞋', 899.0, 320.0, 80),
      ('prod_ecom_headphone', 'ecommerce', 'mgr_elec_01', '无线降噪头戴式耳机 Pro', 'electronics', '主动混合降噪超长续航', 499.0, 180.0, 30)
    ON CONFLICT (id) DO UPDATE SET price = EXCLUDED.price, stock = EXCLUDED.stock;
  `);

  // 3. 商品 SKU 规格种子
  await pool.query(`
    INSERT INTO product_skus (id, business_id, product_id, sku_code, spec_attributes, price, cost_price, stock, image_url, status)
    VALUES
      ('sku_nike_aj1_blk_42', 'nike', 'prod_nike_air_jordan_1', 'NK-AJ1-001-42', '{"color": "黑白芝加哥", "size": "42", "version": "高帮经典"}', 1299.0, 450.0, 20, '/images/aj1_black.png', 'active'),
      ('sku_nike_aj1_blk_425', 'nike', 'prod_nike_air_jordan_1', 'NK-AJ1-001-425', '{"color": "黑白芝加哥", "size": "42.5", "version": "高帮经典"}', 1299.0, 450.0, 15, '/images/aj1_black.png', 'active'),
      ('sku_nike_aj1_red_43', 'nike', 'prod_nike_air_jordan_1', 'NK-AJ1-002-43', '{"color": "公牛红", "size": "43", "version": "高帮经典"}', 1399.0, 480.0, 0, '/images/aj1_red.png', 'out_of_stock'),
      ('sku_nike_pegasus_blue_42', 'nike', 'prod_nike_pegasus_40', 'NK-PEG-001-42', '{"color": "晴空蓝", "size": "42", "version": "标准版"}', 899.0, 320.0, 45, '/images/pegasus_blue.png', 'active')
    ON CONFLICT (id) DO UPDATE SET stock = EXCLUDED.stock, price = EXCLUDED.price;
  `);

  // 4. 确保订单存在
  await pool.query(`
    INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery, user_id, business_id, total_amount)
    VALUES
      ('ORD-ECOM-889901', 'shipped', '顺丰速运', 'SF1092837465', '2026-08-25', 'user_test_001', 'ecommerce', 299.0),
      ('ORD-NIKE-772201', 'shipped', '顺丰速运', 'SF9938271625', '2026-08-23', 'user_test_001', 'nike', 1299.0)
    ON CONFLICT (order_id) DO NOTHING;
  `);

  // 5. 包裹主表与物流流水
  await pool.query(`
    INSERT INTO logistics_packages (id, business_id, order_id, carrier, carrier_code, tracking_number, status, current_location, courier_name, courier_phone, estimated_delivery)
    VALUES
      ('pkg_sf_1092837465', 'ecommerce', 'ORD-ECOM-889901', '顺丰速运', 'SF', 'SF1092837465', 'delivering', '北京市朝阳区酒仙桥分部', '张师傅', '13812345678', '2026-08-25 18:00:00')
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO logistics_tracks (package_id, occurred_at, location, status, description)
    VALUES
      ('pkg_sf_1092837465', NOW() - INTERVAL '2 hours', '北京市朝阳区酒仙桥网点', 'dispatching', '【北京市】快件已由派件员张师傅（电话：13812345678）正在派送中'),
      ('pkg_sf_1092837465', NOW() - INTERVAL '12 hours', '北京顺义集散中心', 'transporting', '【北京市】快件到达北京顺义集散中心'),
      ('pkg_sf_1092837465', NOW() - INTERVAL '1 day', '上海青浦分拨中心', 'transporting', '【上海市】快件已从上海青浦分拨中心发出'),
      ('pkg_sf_1092837465', NOW() - INTERVAL '2 days', '上海市闵行区网点', 'picked_up', '【上海市】顺丰速运 已揽收')
    ON CONFLICT DO NOTHING;
  `);

  // 6. 商品评价与口碑数据
  await pool.query(`
    INSERT INTO product_reviews (business_id, product_id, sku_id, user_id, user_name, rating, content, fit_feedback, sentiment, merchant_reply)
    VALUES
      ('nike', 'prod_nike_air_jordan_1', 'sku_nike_aj1_blk_42', 'user_002', '球鞋玩家Leo', 5, '脚感和包裹性极佳，正码刚刚好，走线皮质很扎实！', 'true_to_size', 'positive', '感谢对正品专营店的喜爱！'),
      ('nike', 'prod_nike_air_jordan_1', 'sku_nike_aj1_blk_425', 'user_003', '运动达人小明', 5, '顺丰次日达很给力，包装双层加固，上脚很有型。', 'true_to_size', 'positive', null),
      ('nike', 'prod_nike_air_jordan_1', 'sku_nike_aj1_red_43', 'user_004', '跑步小菜鸟', 4, '鞋头前掌偏硬一点点，脚背宽的话建议选大半码。', 'runs_small', 'neutral', '收到反馈，脚背宽厚的朋友可选择大半码哦~')
    ON CONFLICT DO NOTHING;
  `);

  console.log('✅ [DB Seed] 商城高保真物理数据植入成功！');
}

if (import.meta.main) {
  seedMallData()
    .then(() => process.exit(0))
    .catch((err) => {
      console.error('❌ [DB Seed] Failed:', err);
      process.exit(1);
    });
}
