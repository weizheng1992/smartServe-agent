import { drizzle } from 'drizzle-orm/node-postgres';
import pg from 'pg';
import * as schema from './schema';

const { Pool } = pg;

// 优先读取商户独立数据库连接串，默认使用 agent_merchant 独立库
const MERCHANT_DB_URL =
  process.env.MERCHANT_DATABASE_URL ||
  process.env.DATABASE_URL?.replace(/\/[^/]+$/, '/agent_merchant') ||
  'postgres://agent_user:agent_password@localhost:5432/agent_merchant';

let merchantPoolInstance: pg.Pool | null = null;
let tablesInitialized = false;

/**
 * 获取商户独立数据库连接池
 */
export function getMerchantPgPool(): pg.Pool {
  if (!merchantPoolInstance) {
    merchantPoolInstance = new Pool({
      connectionString: MERCHANT_DB_URL,
      max: 10,
      idleTimeoutMillis: 30000,
      connectionTimeoutMillis: 5000,
    });

    merchantPoolInstance.on('error', (err) => {
      console.error('❌ Merchant DB Pool Error:', err);
    });
  }
  return merchantPoolInstance;
}

/**
 * 商户 Drizzle ORM 客户端
 */
export const merchantDb = drizzle(getMerchantPgPool(), { schema });

/**
 * 自愈式初始化商户独立物理数据表
 */
export async function ensureMerchantDatabaseAndTables(): Promise<void> {
  if (tablesInitialized) return;

  const pool = getMerchantPgPool();

  try {
    // 确保 DDL 结构存在
    await pool.query(`
      CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

      CREATE TABLE IF NOT EXISTS merchant_spus (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        spu_code TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL,
        subtitle TEXT,
        description TEXT,
        category TEXT NOT NULL DEFAULT '服装鞋包',
        brand TEXT NOT NULL DEFAULT 'AURORA 极光',
        main_image TEXT NOT NULL,
        banner_images JSONB DEFAULT '[]'::jsonb,
        spec_dimensions JSONB DEFAULT '[]'::jsonb,
        specs JSONB DEFAULT '{}'::jsonb,
        status TEXT NOT NULL DEFAULT 'ON_SALE',
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS merchant_skus (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        spu_id UUID NOT NULL REFERENCES merchant_spus(id) ON DELETE CASCADE,
        sku_code TEXT NOT NULL UNIQUE,
        sku_title TEXT NOT NULL,
        spec_attributes JSONB NOT NULL,
        price NUMERIC(10,2) NOT NULL,
        original_price NUMERIC(10,2),
        stock INTEGER NOT NULL DEFAULT 0,
        locked_stock INTEGER NOT NULL DEFAULT 0,
        image_url TEXT,
        barcode TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS merchant_customers (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        customer_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT,
        member_level TEXT NOT NULL DEFAULT 'VIP',
        addresses JSONB DEFAULT '[]'::jsonb,
        tags JSONB DEFAULT '[]'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS merchant_orders (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        order_id TEXT NOT NULL UNIQUE,
        customer_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PAID',
        total_amount NUMERIC(10,2) NOT NULL,
        currency TEXT NOT NULL DEFAULT 'CNY',
        shipping_address JSONB NOT NULL,
        tracking_info JSONB,
        is_returnable BOOLEAN NOT NULL DEFAULT TRUE,
        is_address_modifiable BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS merchant_order_items (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        order_id TEXT NOT NULL REFERENCES merchant_orders(order_id) ON DELETE CASCADE,
        spu_id TEXT NOT NULL,
        sku_code TEXT NOT NULL,
        title TEXT NOT NULL,
        sku_title TEXT NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        price NUMERIC(10,2) NOT NULL,
        image_url TEXT,
        spec_summary TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS merchant_audit_logs (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        action_type TEXT NOT NULL,
        order_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        operator TEXT NOT NULL DEFAULT 'AGENT_SPI',
        payload JSONB DEFAULT '{}'::jsonb,
        result JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
      );
    `);

    tablesInitialized = true;
  } catch (err: any) {
    // 如果目标数据库不存在 (3D000: database does not exist)，尝试在 default postgres 库中创建
    if (err.code === '3D000') {
      const defaultUrl = MERCHANT_DB_URL.replace(/\/[^/]+$/, '/agent_platform');
      const adminPool = new Pool({ connectionString: defaultUrl });
      try {
        await adminPool.query(`CREATE DATABASE agent_merchant;`);
      } catch (createErr: any) {
        // 若已存在忽略
      } finally {
        await adminPool.end();
      }
      // 重试建表
      return ensureMerchantDatabaseAndTables();
    }
    throw err;
  }
}
