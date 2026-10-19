"""parity 册(ADR-0015 批一全量):本体声明编译产物与 engine semantic_model
现行运行时结构逐键相等 —— 12 实体 / 9 join / 8 维度全量对拍。

单侧漂移(任一方改列/改口径而另一方未跟)在本册红灯,即「三份真相」病症
被前置到加载层消灭。批二 semantic_model.yaml 被吸收时,本册转为吸收守卫。
"""

from __future__ import annotations

from engine_py.tools_registry.semantic_model import SEMANTIC_MODEL
from ontology import (
    BUNDLES,
    ONTOLOGY_ENTITIES,
    semantic_dimension_projection,
    semantic_entity_projection,
    semantic_join_projection,
)

ALL_ENTITIES = (
    # product
    "merchant_spus", "merchant_skus", "merchant_product_reviews",
    # trading
    "merchant_orders", "merchant_order_items",
    # marketing
    "promotions", "promotion_redemptions", "user_coupons",
    # crm
    "merchant_customers",
    # shared
    "merchant_audit_logs", "session_metrics", "after_sale_tickets",
)
ALL_JOINS = (
    "sku_of_spu", "sku_of_spu_strict", "items_of_spu_code", "review_of_spu",
    "items_of_order", "orders_of_customer",
    "redemption_of_promotion", "redemption_of_order", "coupon_of_promotion",
)
ALL_DIMENSIONS = (
    "category", "brand", "spu",
    "order_status", "region", "city",
    "promotion",
    "customer",
)
DOMAIN_COVERAGE = {
    "product": {"merchant_spus", "merchant_skus", "merchant_product_reviews"},
    "trading": {"merchant_orders", "merchant_order_items"},
    "marketing": {"promotions", "promotion_redemptions", "user_coupons"},
    "crm": {"merchant_customers"},
    "shared": {"merchant_audit_logs", "session_metrics", "after_sale_tickets"},
}


def test_domain_coverage_complete() -> None:
    assert set(BUNDLES) == set(DOMAIN_COVERAGE)
    for domain, keys in DOMAIN_COVERAGE.items():
        assert set(BUNDLES[domain].entities) == keys


def test_entity_parity_full() -> None:
    assert set(ONTOLOGY_ENTITIES) == set(SEMANTIC_MODEL["entities"])
    for key in ALL_ENTITIES:
        assert semantic_entity_projection(key) == SEMANTIC_MODEL["entities"][key], (
            f"实体 {key} 本体声明与 semantic_model 漂移 —— 改列/改口径须两侧同批"
        )


def test_join_parity_full() -> None:
    engine_joins = {j["name"]: j for j in SEMANTIC_MODEL["joins"]}
    ontology_joins = {j["name"]: j for j in semantic_join_projection()}
    assert set(ontology_joins) == set(engine_joins)
    for name in ALL_JOINS:
        assert ontology_joins[name] == engine_joins[name], f"join {name} 漂移"


def test_dimension_parity_full() -> None:
    dims = semantic_dimension_projection()
    assert set(dims) == set(SEMANTIC_MODEL["dimensions"])
    for name in ALL_DIMENSIONS:
        assert dims[name] == SEMANTIC_MODEL["dimensions"][name], f"维度 {name} 漂移"


def test_entity_key_equals_table() -> None:
    """批一 约束:声明键与物理表同名(表列映射锚;schema 前缀留批二裁决)。"""
    for key in ALL_ENTITIES:
        assert ONTOLOGY_ENTITIES[key].table == key
