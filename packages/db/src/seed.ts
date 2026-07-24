import { Client } from 'pg';

async function main() {
  const dbUrl = process.env.DATABASE_URL || 'postgres://agent_user:agent_password@localhost:5432/agent_platform';
  console.log('[PG Seed] 启动 100% 纯血 PostgreSQL Drizzle 物理数据注入...');
  console.log('[PG Seed] 目标连接 URL:', dbUrl);

  const client = new Client({ connectionString: dbUrl });

  try {
    await client.connect();

    // Force DROP historical tables with column case conflicts to guarantee a 100% successful clean install!
    console.log('[PG Seed] 正在清理物理 PostgreSQL 遗留的旧版 table 结构冲突...');
    await client.query('DROP TABLE IF EXISTS orders CASCADE');

    // 100% Secure lowercase snake_case orders table construction
    await client.query(`
      CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        carrier TEXT NOT NULL,
        tracking_number TEXT NOT NULL,
        estimated_delivery TEXT NOT NULL
      )
    `);

    // Injects/Saves physical live ORD-98712
    await client.query(`
      INSERT INTO orders (order_id, status, carrier, tracking_number, estimated_delivery)
      VALUES ('ORD-98712', 'shipped', 'FedEx', '1234567890', '2026-07-20')
      ON CONFLICT (order_id) DO UPDATE SET
        status = EXCLUDED.status,
        carrier = EXCLUDED.carrier,
        tracking_number = EXCLUDED.tracking_number,
        estimated_delivery = EXCLUDED.estimated_delivery
    `);

    console.log('✅ [PG Seed] PostgreSQL 物理 Seeding 完美完成！ORD-98712 已成功落盘数据库！');

    const check = await client.query('SELECT * FROM orders');
    console.log('[PG Seed] 数据库中当前最新的 orders 真实记录:\n', check.rows);

    await client.end();
  } catch (err: any) {
    console.error('❌ [PG Seed] PostgreSQL Seeding 失败:', err.message);
  }
}

main();
