import { getPgPool } from "./client";

async function migrateColumns() {
  const pool = getPgPool();
  console.log("[DB Migration] 正在更新 products 与 order_items 物理表字段...");

  await pool.query(`
    ALTER TABLE products ADD COLUMN IF NOT EXISTS manager_id text;
    ALTER TABLE products ADD COLUMN IF NOT EXISTS category text DEFAULT 'general';
    ALTER TABLE products ADD COLUMN IF NOT EXISTS cost_price real DEFAULT 0.0;
    ALTER TABLE order_items ADD COLUMN IF NOT EXISTS cost_at_purchase real DEFAULT 0.0;
  `);

  console.log("✅ [DB Migration] 物理表列字段扩展完成！");
}

migrateColumns()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("❌ [DB Migration] Failed:", err);
    process.exit(1);
  });
