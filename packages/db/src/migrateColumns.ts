import { getPgPool } from './client';

async function migrateColumns() {
  const pool = getPgPool();
  console.log('[DB Migration] 正在更新 products 与 order_items 物理表字段...');

  await pool.query(`
    ALTER TABLE products ADD COLUMN IF NOT EXISTS manager_id text;
    ALTER TABLE products ADD COLUMN IF NOT EXISTS category text DEFAULT 'general';
    ALTER TABLE products ADD COLUMN IF NOT EXISTS cost_price real DEFAULT 0.0;
    ALTER TABLE order_items ADD COLUMN IF NOT EXISTS cost_at_purchase real DEFAULT 0.0;

    -- Orders additional delivery fields and address relationship
    ALTER TABLE orders ADD COLUMN IF NOT EXISTS address_id uuid;
    ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_address text;
    ALTER TABLE orders ADD COLUMN IF NOT EXISTS recipient_name text;
    ALTER TABLE orders ADD COLUMN IF NOT EXISTS phone text;
    ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at timestamp DEFAULT NOW();

    -- Dual-tier scoped persona columns
    ALTER TABLE long_memory_facts ADD COLUMN IF NOT EXISTS business_id text;
    ALTER TABLE long_memory_facts ADD COLUMN IF NOT EXISTS scope text DEFAULT 'global';
    CREATE INDEX IF NOT EXISTS long_facts_user_scope_biz_idx ON long_memory_facts (user_id, scope, business_id);

    ALTER TABLE episodic_events ADD COLUMN IF NOT EXISTS business_id text;
    ALTER TABLE episodic_events ADD COLUMN IF NOT EXISTS scope text DEFAULT 'global';
    CREATE INDEX IF NOT EXISTS episodic_user_scope_biz_idx ON episodic_events (user_id, scope, business_id);

    -- Multi-tenant Conversation & Messages extension
    ALTER TABLE threads DROP CONSTRAINT IF EXISTS threads_user_id_fkey;
    ALTER TABLE threads ALTER COLUMN user_id TYPE text USING user_id::text;
    ALTER TABLE threads ADD COLUMN IF NOT EXISTS assigned_operator_id text;
    ALTER TABLE threads ADD COLUMN IF NOT EXISTS unread_count integer DEFAULT 0;
    ALTER TABLE threads ADD COLUMN IF NOT EXISTS tags jsonb DEFAULT '[]'::jsonb;
    ALTER TABLE threads ADD COLUMN IF NOT EXISTS metadata jsonb DEFAULT '{}'::jsonb;
    CREATE INDEX IF NOT EXISTS threads_biz_status_idx ON threads (business_id, status);
    CREATE INDEX IF NOT EXISTS threads_updated_at_idx ON threads (updated_at);

    ALTER TABLE messages ADD COLUMN IF NOT EXISTS business_id text;
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS thought_steps jsonb;
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS tool_calls jsonb;
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS cards jsonb;
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS operator_info jsonb;
    ALTER TABLE messages ADD COLUMN IF NOT EXISTS created_at timestamp DEFAULT NOW();
    CREATE INDEX IF NOT EXISTS messages_thread_idx ON messages (thread_id);
    CREATE INDEX IF NOT EXISTS messages_biz_thread_idx ON messages (business_id, thread_id);

    -- Tenant configs extension
    ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS enabled_skills jsonb;
    ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS skills_config jsonb;

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

  console.log('✅ [DB Migration] 物理表列字段扩展完成！');
}

migrateColumns()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error('❌ [DB Migration] Failed:', err);
    process.exit(1);
  });
