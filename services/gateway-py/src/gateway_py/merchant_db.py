"""商户独立物理库(agent_merchant)— 移植 apps/merchant/src/db/merchantDb.ts。

连接串解析:MERCHANT_DATABASE_URL → DATABASE_URL 改库名为 agent_merchant → 默认。
自愈:库不存在(3D000)时先在 agent_platform 库里 CREATE DATABASE 再重试建表。
"""

from __future__ import annotations

import os
import re

from engine_py.config import settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_MERCHANT_DDL = """
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

-- ADR-0003 Q1:成本价(当前采购进价)+ 明细成交进价快照 —— 毛利精确口径
ALTER TABLE merchant_skus ADD COLUMN IF NOT EXISTS cost_price NUMERIC(10,2) NOT NULL DEFAULT 0;
ALTER TABLE merchant_orders ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(10,2) NOT NULL DEFAULT 0;
ALTER TABLE merchant_orders ADD COLUMN IF NOT EXISTS promo_id UUID;
ALTER TABLE merchant_order_items ADD COLUMN IF NOT EXISTS cost_at_purchase NUMERIC(10,2) NOT NULL DEFAULT 0;

-- 商品评价(2026-09-13):「评价好的X」检索/查询的真实数据面 —— 此前
-- product_reviews 挂 engine 本地 products 域且 0 行,评价诉求全链无数据。
-- 评价挂在商户 SPU 上,与聊天/商城同一商品身份(spu_id)。
CREATE TABLE IF NOT EXISTS merchant_product_reviews (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  spu_id UUID NOT NULL,
  sku_code TEXT,
  customer_id TEXT,
  rating INT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_merchant_reviews_spu ON merchant_product_reviews(spu_id);

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

CREATE TABLE IF NOT EXISTS promotions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  promo_type TEXT NOT NULL,             -- full_reduction | discount | coupon
  threshold_amount NUMERIC(10,2),       -- 满减门槛(full_reduction)
  discount_value NUMERIC(10,2) NOT NULL,-- 满减额 / 折扣%(85=8.5折) / 券面额
  scope_type TEXT NOT NULL DEFAULT 'all',-- all | spu | category
  scope_value TEXT,                     -- spu_code 或品类名
  status TEXT NOT NULL DEFAULT 'active',-- active | disabled
  start_at TIMESTAMP NOT NULL DEFAULT NOW(),
  end_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS promotion_redemptions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  promotion_id UUID NOT NULL,
  order_id TEXT NOT NULL,
  discount_amount NUMERIC(10,2) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_coupons (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  promotion_id UUID NOT NULL,
  user_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'claimed',  -- claimed | used
  used_order_id TEXT,
  claimed_at TIMESTAMP NOT NULL DEFAULT NOW(),
  used_at TIMESTAMP
);

-- 券约束补齐(2026-09-22):此前唯一约束只存在于测试 DDL,正式库裸表 ——
-- 防重复领取仅有应用层查重(存在并发窗口),孤儿行无人拦。幂等迁移:
-- pg_constraint 探测后补建;老库存量若已有重复/孤儿行,约束会建失败,
-- 需先清数(结算/领券的最终防线是 mark_coupon_used 条件更新,非本约束)。
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_user_promo'
                 AND conrelid = 'user_coupons'::regclass) THEN
    ALTER TABLE user_coupons ADD CONSTRAINT uq_user_promo UNIQUE (promotion_id, user_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_user_coupons_promotion'
                 AND conrelid = 'user_coupons'::regclass) THEN
    ALTER TABLE user_coupons ADD CONSTRAINT fk_user_coupons_promotion
      FOREIGN KEY (promotion_id) REFERENCES promotions(id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_redemptions_promotion'
                 AND conrelid = 'promotion_redemptions'::regclass) THEN
    ALTER TABLE promotion_redemptions ADD CONSTRAINT fk_redemptions_promotion
      FOREIGN KEY (promotion_id) REFERENCES promotions(id);
  END IF;
END $$;
"""


def _merchant_db_url() -> str:
    url = os.environ.get("MERCHANT_DATABASE_URL")
    if url:
        return url
    base = settings.database_url
    if base:
        return re.sub(r"/[^/]+$", "/agent_merchant", base)
    return "postgres://agent_user:agent_password@localhost:5432/agent_merchant"


def _platform_db_url() -> str:
    # 平台库真实 URL 优先取 settings(测试容器库名由 testcontainers 生成,并非
    # agent_platform;2026-09-05 前硬编码字面量导致自愈在全新实例上必败)
    if settings.database_url:
        return settings.database_url
    return re.sub(r"/[^/]+$", "/agent_platform", _merchant_db_url())


def _normalize(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


_engine = create_async_engine(_normalize(_merchant_db_url()), pool_size=10, max_overflow=0, pool_pre_ping=True)
_tables_initialized = False


async def ensure_merchant_tables() -> None:
    global _tables_initialized
    if _tables_initialized:
        return
    try:
        async with _engine.begin() as conn:
            # _MERCHANT_DDL 为多语句脚本;asyncpg 预编译协议不支持,
            # 走原始连接 simple-query 协议执行
            raw = (await conn.get_raw_connection()).driver_connection
            await raw.execute(_MERCHANT_DDL)
    except Exception as err:
        if "3D000" not in repr(err) and "InvalidCatalogName" not in type(err).__name__:
            raise
        # CREATE DATABASE 不能在事务块内执行:引擎必须 AUTOCOMMIT,否则
        # ActiveSQLTransactionError 会被下面的 except 吞掉、库始终建不成,
        # 自愈形同虚设(2026-09-05 于全新测试容器上首次暴露)
        bootstrap = create_async_engine(_normalize(_platform_db_url()), isolation_level="AUTOCOMMIT")
        try:
            async with bootstrap.connect() as conn:
                await conn.execute(text("CREATE DATABASE agent_merchant"))
        except Exception as err:
            print(f"[MerchantDB] 自愈建库跳过(通常为库已存在): {err!r}")
        finally:
            await bootstrap.dispose()
        async with _engine.begin() as conn:
            # 与首尝试一致:多语句 DDL 须走 simple-query 协议,
            # prepared protocol 不接受多命令(2026-09-05 修复)
            raw = (await conn.get_raw_connection()).driver_connection
            await raw.execute(_MERCHANT_DDL)
    _tables_initialized = True


def merchant_engine():
    return _engine
