"""parity 册(ADR-0015 批〇核心验收):本体声明编译产物与 engine
semantic_model 现行运行时结构逐键相等 —— 证明「声明 → 编译 → 运行时同构」
环闭合,批二接管 schema 卡/manifest 前的迁移守卫。

单侧漂移(任一方改列/改口径而另一方未跟)在本册红灯,即「三份真相」
病症被前置到加载层消灭。
"""

from __future__ import annotations

from engine_py.tools_registry.semantic_model import SEMANTIC_MODEL

from ontology import (
    BUNDLES,
    semantic_dimension_projection,
    semantic_entity_projection,
    semantic_join_projection,
)

MARKETING_ENTITIES = ("promotions", "promotion_redemptions", "user_coupons")
# 批〇 域内闭合:跨域 join redemption_of_order(table=merchant_orders)随
# trading.yaml 批一落位后并入本元组。
MARKETING_JOINS = ("redemption_of_promotion", "coupon_of_promotion")


def test_marketing_bundle_loaded() -> None:
    assert "marketing" in BUNDLES
    assert tuple(sorted(BUNDLES["marketing"].entities)) == tuple(sorted(MARKETING_ENTITIES))


def test_entity_parity_five_keys() -> None:
    for key in MARKETING_ENTITIES:
        assert semantic_entity_projection(key) == SEMANTIC_MODEL["entities"][key], (
            f"实体 {key} 本体声明与 semantic_model 漂移 —— 改列/改口径须两侧同批"
        )


def test_join_parity() -> None:
    engine_joins = {j["name"]: j for j in SEMANTIC_MODEL["joins"]}
    ontology_joins = {j["name"]: j for j in semantic_join_projection()}
    for name in MARKETING_JOINS:
        assert ontology_joins[name] == engine_joins[name], f"join {name} 漂移"


def test_dimension_parity() -> None:
    dims = semantic_dimension_projection()
    assert "promotion" in dims
    assert dims["promotion"] == SEMANTIC_MODEL["dimensions"]["promotion"]


def test_entity_key_equals_table() -> None:
    """批〇 约束:声明键与物理表同名(表列映射锚;schema 前缀留批二裁决)。"""
    for key in MARKETING_ENTITIES:
        assert BUNDLES["marketing"].entities[key].table == key
