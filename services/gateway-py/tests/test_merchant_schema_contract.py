"""商户真账库 schema 契约(2026-10-18 三份 DDL 真相收口,critic#3)。

商户库表形此前有三份真相并行演进:`_MERCHANT_DDL`(gateway_py/merchant_db.py,
唯一建库源)、九册测试的手写 INSERT 列清单(已收敛 merchant_seed_helpers)、
以及各处裸 SQL 的列引用 —— 加列漏同步任一份即静默列缺失(f45ea23 实弹:
缺列窄形状传染 43 挂)。本册把「活库列集」钉进冻结 manifest:

- **加列流程**:`_MERCHANT_DDL` 加列 → 本 manifest 同步 → (涉行形状时)
  `tests/merchant_seed_helpers.py` 列清单同步 → 跑本册红灯转绿;
- 本册只比**列名集合**(类型/默认值由 DDL 单点管),漏列/多列都以可行动文案
  点名,不再让漂移以 43 个下游失败的形式显形。
"""

from __future__ import annotations

from sqlalchemy import text

from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine

# 冻结 manifest(与 _MERCHANT_DDL 同源;2026-10-18 起冻结,含全部幂等 ALTER 后终态)
MANIFEST: dict[str, set[str]] = {
    "merchant_spus": {
        "id", "spu_code", "title", "subtitle", "description", "category", "brand",
        "main_image", "banner_images", "spec_dimensions", "specs", "status",
        "created_at", "updated_at", "owner_id",
    },
    "merchant_skus": {
        "id", "spu_id", "sku_code", "sku_title", "spec_attributes", "price",
        "original_price", "stock", "locked_stock", "image_url", "barcode",
        "cost_price", "created_at", "updated_at",
    },
    "merchant_customers": {
        "id", "customer_id", "name", "phone", "email", "member_level",
        "addresses", "tags", "created_at", "updated_at",
    },
    "merchant_orders": {
        "id", "order_id", "business_id", "customer_id", "status", "total_amount",
        "discount_amount", "promo_id", "currency", "shipping_address", "tracking_info",
        "is_returnable", "is_address_modifiable", "created_at", "updated_at",
    },
    "merchant_order_items": {
        "id", "order_id", "spu_id", "sku_code", "title", "sku_title", "quantity",
        "price", "image_url", "spec_summary", "cost_at_purchase", "created_at",
    },
    "merchant_product_reviews": {
        "id", "spu_id", "sku_code", "customer_id", "rating", "content", "created_at",
    },
    "merchant_audit_logs": {
        "id", "action_type", "order_id", "idempotency_key", "operator",
        "payload", "result", "created_at",
    },
    "promotions": {
        "id", "business_id", "name", "promo_type", "threshold_amount",
        "discount_value", "scope_type", "scope_value", "status", "start_at",
        "end_at", "created_at", "total_quota", "created_by",
    },
    "promotion_redemptions": {
        "id", "promotion_id", "order_id", "discount_amount", "created_at",
    },
    "user_coupons": {
        "id", "business_id", "promotion_id", "user_id", "status",
        "used_order_id", "claimed_at", "used_at",
    },
    "thread_notes": {
        "id", "thread_id", "business_id", "author_email", "content", "created_at",
    },
    "owner_mappings": {
        "id", "business_id", "map_type", "map_value", "staff_id", "owner_type",
        "created_at", "updated_at",
    },
}


async def test_merchant_schema_matches_manifest(contract_fixtures):
    await ensure_merchant_tables()
    async with merchant_engine().connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = ANY(:ts)"
                ).bindparams(ts=sorted(MANIFEST))
            )
        ).all()
    live: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        live.setdefault(table_name, set()).add(column_name)

    problems: list[str] = []
    for table, expected in MANIFEST.items():
        actual = live.get(table)
        if actual is None:
            problems.append(f"{table}: 表不存在")
            continue
        missing = expected - actual
        extra = actual - expected
        if missing:
            problems.append(f"{table}: manifest 有而库缺 {sorted(missing)}(DDL 未跑/表形回退)")
        if extra:
            problems.append(
                f"{table}: 库有而 manifest 缺 {sorted(extra)} —— 新加列未同步清单,"
                "流程:_MERCHANT_DDL → 本 manifest → merchant_seed_helpers 列清单"
            )
    extra_tables = sorted(set(live) - set(MANIFEST))
    if extra_tables:
        problems.append(f"manifest 外多出商户表 {extra_tables}(新表须同步登记)")
    assert not problems, "商户库 schema 漂移:\n" + "\n".join(problems)
