"""第三方商户物理表 + 极光潮品租户注册 — 移植 packages/db/src/seedThirdPartyMerchant.ts。

third_party_* 表不归 Drizzle/Alembic 管(原 TS 也是裸 DDL 自建),继续由本脚本幂等维护。

用法::

    cd services/engine-py && uv run python -m engine_py.db.seed_third_party
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from .session import _engine

_DDL = """
ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS spi_config JSONB;
ALTER TABLE tenant_configs ADD COLUMN IF NOT EXISTS enabled_skills JSONB;

CREATE TABLE IF NOT EXISTS third_party_customers (
  customer_id TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  external_email TEXT,
  customer_name TEXT NOT NULL,
  phone_number TEXT,
  vip_tier TEXT DEFAULT 'GOLD',
  delivery_addresses JSONB,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS third_party_orders (
  ext_order_sn TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  order_status TEXT NOT NULL,
  order_currency TEXT DEFAULT 'CNY',
  pay_amount REAL NOT NULL,
  recipient_name TEXT NOT NULL,
  recipient_phone TEXT NOT NULL,
  shipping_address TEXT NOT NULL,
  carrier_code TEXT,
  tracking_no TEXT,
  can_modify_address BOOLEAN DEFAULT TRUE,
  can_refund BOOLEAN DEFAULT TRUE,
  order_time TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS third_party_order_items (
  item_id TEXT PRIMARY KEY,
  ext_order_sn TEXT NOT NULL REFERENCES third_party_orders(ext_order_sn) ON DELETE CASCADE,
  sku_code TEXT NOT NULL,
  item_title TEXT NOT NULL,
  unit_price REAL NOT NULL,
  buy_qty INTEGER NOT NULL,
  item_pic_url TEXT
);

CREATE TABLE IF NOT EXISTS third_party_inventory (
  sku_code TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  item_title TEXT NOT NULL,
  category_name TEXT DEFAULT 'fashion',
  selling_price REAL NOT NULL,
  available_qty INTEGER DEFAULT 50,
  is_on_shelf BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS third_party_audit_logs (
  action_id TEXT PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  ext_order_sn TEXT NOT NULL,
  action_type TEXT NOT NULL,
  idempotency_token TEXT NOT NULL,
  received_signature TEXT,
  payload JSONB,
  executed_at TIMESTAMP DEFAULT NOW()
);
"""

_TENANT_SQL = """
INSERT INTO tenants (id, business_id, name, plan_tier, status)
VALUES ('a0000000-0000-0000-0000-000000000001', 'aurora', '极光潮品官方旗舰店', 'enterprise', 'active')
ON CONFLICT (business_id) DO UPDATE SET
  name = EXCLUDED.name,
  status = EXCLUDED.status;

INSERT INTO tenant_configs (id, business_id, system_prompt, welcome_message, status, version, spi_config, enabled_skills)
VALUES (
  'b0000000-0000-0000-0000-000000000001',
  'aurora',
  'You are the official AI Customer Support Agent for 极光潮品 (Aurora Luxe). Help customers with order shipping tracking, fast address modification, refund requests, and product inventory inquiry via remote SPI.',
  '您好！我是极光潮品官方智能客服。请问有什么可以帮您？',
  'published',
  1,
  '{"mode": "remote_spi", "spiBaseUrl": "http://localhost:3005", "apiSecret": "aurora_secret_key_8899", "timeoutMs": 5000}'::jsonb,
  '["skill_order_address_modification", "skill_order_refund", "skill_product_inquiry"]'::jsonb
)
ON CONFLICT (id) DO UPDATE SET
  spi_config = EXCLUDED.spi_config,
  system_prompt = EXCLUDED.system_prompt;
"""

_PRODUCTS = [
    ("AURORA-SKU-001", "aurora", "极光纯棉重磅短袖T恤 (220g重磅)", "apparel", 129.0, 180),
    ("AURORA-SKU-002", "aurora", "极光轻量三防连帽冲锋衣 (暴雨级防水)", "outerwear", 499.0, 85),
    ("AURORA-SKU-003", "aurora", "极光经典立体剪裁工装裤 (耐磨抗皱)", "pants", 259.0, 120),
    ("AURORA-SKU-004", "aurora", "极光复古气垫缓震慢跑鞋 (全掌缓震)", "shoes", 399.0, 65),
]

_ADDRESSES = [
    {
        "id": "ADDR-101",
        "recipientName": "张伟",
        "phone": "13800138000",
        "fullAddress": "北京市海淀区中关村南大街1号院8号楼1201室",
        "province": "北京市",
        "city": "北京市",
        "district": "海淀区",
        "isDefault": True,
    },
    {
        "id": "ADDR-102",
        "recipientName": "张伟(公司)",
        "phone": "13800138000",
        "fullAddress": "北京市朝阳区望京SOHO T1座 1508室",
        "province": "北京市",
        "city": "北京市",
        "district": "朝阳区",
        "isDefault": False,
    },
]


async def seed_third_party_merchant() -> None:
    print("[SeedMerchant] Initializing third-party merchant physical tables and seed data...")
    async with _engine.begin() as conn:
        await conn.execute(text(_DDL))
        await conn.execute(text(_TENANT_SQL))

        for sku_code, merchant_id, item_title, category_name, selling_price, available_qty in _PRODUCTS:
            await conn.execute(
                text(
                    "INSERT INTO third_party_inventory (sku_code, merchant_id, item_title, category_name, "
                    "selling_price, available_qty, is_on_shelf) VALUES (:s, :m, :t, :c, :p, :q, TRUE) "
                    "ON CONFLICT (sku_code) DO UPDATE SET selling_price = EXCLUDED.selling_price, "
                    "available_qty = EXCLUDED.available_qty, item_title = EXCLUDED.item_title"
                ),
                {"s": sku_code, "m": merchant_id, "t": item_title, "c": category_name, "p": selling_price, "q": available_qty},
            )

        await conn.execute(
            text(
                "INSERT INTO third_party_customers (customer_id, merchant_id, external_email, customer_name, "
                "phone_number, vip_tier, delivery_addresses) VALUES (:c, :m, :e, :n, :p, :v, :a) "
                "ON CONFLICT (customer_id) DO UPDATE SET delivery_addresses = EXCLUDED.delivery_addresses, "
                "customer_name = EXCLUDED.customer_name"
            ),
            {
                "c": "CUST-8801",
                "m": "aurora",
                "e": "zhangwei@example.com",
                "n": "张伟",
                "p": "13800138000",
                "v": "DIAMOND",
                "a": json.dumps(_ADDRESSES, ensure_ascii=False),
            },
        )

        await conn.execute(
            text(
                "INSERT INTO third_party_orders (ext_order_sn, merchant_id, customer_id, order_status, pay_amount, "
                "recipient_name, recipient_phone, shipping_address, can_modify_address, can_refund) "
                "VALUES (:o, :m, :c, 'PAID', :p, :n, :ph, :a, TRUE, TRUE) "
                "ON CONFLICT (ext_order_sn) DO UPDATE SET order_status = EXCLUDED.order_status, "
                "shipping_address = EXCLUDED.shipping_address, can_modify_address = EXCLUDED.can_modify_address"
            ),
            {
                "o": "AURORA-ORD-2026-9081",
                "m": "aurora",
                "c": "CUST-8801",
                "p": 499.0,
                "n": "张伟",
                "ph": "13800138000",
                "a": "北京市海淀区中关村南大街1号院8号楼1201室",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO third_party_order_items (item_id, ext_order_sn, sku_code, item_title, unit_price, buy_qty) "
                "VALUES (:i, :o, :s, :t, :p, :q) ON CONFLICT (item_id) DO NOTHING"
            ),
            {
                "i": "ITEM-9081-1",
                "o": "AURORA-ORD-2026-9081",
                "s": "AURORA-SKU-002",
                "t": "极光轻量三防连帽冲锋衣 (暴雨级防水)",
                "p": 499.0,
                "q": 1,
            },
        )

        await conn.execute(
            text(
                "INSERT INTO third_party_orders (ext_order_sn, merchant_id, customer_id, order_status, pay_amount, "
                "recipient_name, recipient_phone, shipping_address, carrier_code, tracking_no, "
                "can_modify_address, can_refund) "
                "VALUES (:o, :m, :c, 'SHIPPED', :p, :n, :ph, :a, 'SF', :t, FALSE, TRUE) "
                "ON CONFLICT (ext_order_sn) DO UPDATE SET order_status = EXCLUDED.order_status, "
                "tracking_no = EXCLUDED.tracking_no, can_modify_address = EXCLUDED.can_modify_address"
            ),
            {
                "o": "AURORA-ORD-2026-9082",
                "m": "aurora",
                "c": "CUST-8801",
                "p": 129.0,
                "n": "张伟",
                "ph": "13800138000",
                "a": "北京市海淀区中关村南大街1号院8号楼1201室",
                "t": "SF18928374619",
            },
        )
        await conn.execute(
            text(
                "INSERT INTO third_party_order_items (item_id, ext_order_sn, sku_code, item_title, unit_price, buy_qty) "
                "VALUES (:i, :o, :s, :t, :p, :q) ON CONFLICT (item_id) DO NOTHING"
            ),
            {
                "i": "ITEM-9082-1",
                "o": "AURORA-ORD-2026-9082",
                "s": "AURORA-SKU-001",
                "t": "极光纯棉重磅短袖T恤 (220g重磅)",
                "p": 129.0,
                "q": 1,
            },
        )

    await _engine.dispose()
    print("[SeedMerchant] Third-party merchant database tables & seed data initialized successfully.")


if __name__ == "__main__":
    asyncio.run(seed_third_party_merchant())
