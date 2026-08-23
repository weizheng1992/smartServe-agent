import { getPgPool } from "./client";

async function migrateColumns() {
  const pool = getPgPool();
  console.log("[DB Migration] 正在更新 products 与 order_items 物理表字段...");

  await pool.query(`
    ALTER TABLE products ADD COLUMN IF NOT EXISTS manager_id text;
    ALTER TABLE products ADD COLUMN IF NOT EXISTS category text DEFAULT 'general';
    ALTER TABLE products ADD COLUMN IF NOT EXISTS cost_price real DEFAULT 0.0;
    ALTER TABLE order_items ADD COLUMN IF NOT EXISTS cost_at_purchase real DEFAULT 0.0;

    -- Dual-tier scoped persona columns
    ALTER TABLE long_memory_facts ADD COLUMN IF NOT EXISTS business_id text;
    ALTER TABLE long_memory_facts ADD COLUMN IF NOT EXISTS scope text DEFAULT 'global';
    CREATE INDEX IF NOT EXISTS long_facts_user_scope_biz_idx ON long_memory_facts (user_id, scope, business_id);

    ALTER TABLE episodic_events ADD COLUMN IF NOT EXISTS business_id text;
    ALTER TABLE episodic_events ADD COLUMN IF NOT EXISTS scope text DEFAULT 'global';
    CREATE INDEX IF NOT EXISTS episodic_user_scope_biz_idx ON episodic_events (user_id, scope, business_id);

    -- Transactional outbox table
    CREATE TABLE IF NOT EXISTS approval_outbox_events (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      approval_id TEXT NOT NULL,
      thread_id TEXT NOT NULL,
      event_type TEXT NOT NULL,
      payload JSONB NOT NULL,
      status TEXT DEFAULT 'pending' NOT NULL,
      retry_count INTEGER DEFAULT 0 NOT NULL,
      error_message TEXT,
      created_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS approval_outbox_status_idx ON approval_outbox_events (status, created_at);
    CREATE INDEX IF NOT EXISTS approval_outbox_approval_idx ON approval_outbox_events (approval_id);
  `);

  console.log("✅ [DB Migration] 物理表列字段扩展完成！");
}

migrateColumns()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("❌ [DB Migration] Failed:", err);
    process.exit(1);
  });
