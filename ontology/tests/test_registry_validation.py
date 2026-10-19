"""校验负例册:坏声明必须响亮失败(进程起不来),不静默跳过 —— 与
engine semantic_model.py / metric_registry.py 同纪律。

全部用例直接喂 build_ontology 纯函数坏数据,零文件系统依赖。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ontology import CORE, build_core, build_ontology

MARKETING_YAML: dict = {
    "version": 1,
    "domain": "marketing",
    "entities": {
        "promotions": {
            "table": "promotions",
            "database": "merchant_db",
            "alias": "p",
            "label": "优惠活动",
            "columns": {"id": "主键", "name": "活动名"},
            "notes": "",
        },
        "promotion_redemptions": {
            "table": "promotion_redemptions",
            "database": "merchant_db",
            "alias": "rd",
            "label": "活动核销",
            "columns": {"promotion_id": "→ promotions.id", "order_id": "订单"},
            "notes": "",
        },
    },
    "joins": [
        {
            "name": "redemption_of_promotion",
            "table": "promotions",
            "base": "promotion_redemptions",
            "type": "inner",
            "condition": "p.id = rd.promotion_id",
        }
    ],
    "dimensions": {
        "promotion": {
            "label": "活动",
            "kind": "entity",
            "entity": "promotions",
            "id_column": "id",
            "label_column": "name",
        }
    },
}


def _marketing(**overrides) -> dict:
    data = {k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)) for k, v in MARKETING_YAML.items()}
    data.update(overrides)
    return data


def test_baseline_build_passes() -> None:
    bundles = build_ontology(CORE, [_marketing()])
    assert "marketing" in bundles


def test_unknown_domain_rejected() -> None:
    with pytest.raises(ValueError, match="未知领域"):
        build_ontology(CORE, [_marketing(domain="logistics")])


def test_bad_version_rejected() -> None:
    with pytest.raises(ValueError, match="不支持的版本"):
        build_ontology(CORE, [_marketing(version=2)])


def test_unknown_database_rejected() -> None:
    bad = _marketing()
    bad["entities"]["promotions"] = {**bad["entities"]["promotions"], "database": "sqlite"}
    with pytest.raises(ValueError, match="databases 闭集"):
        build_ontology(CORE, [bad])


def test_empty_columns_rejected() -> None:
    bad = _marketing()
    bad["entities"]["promotions"] = {**bad["entities"]["promotions"], "columns": {}}
    with pytest.raises(ValidationError):
        build_ontology(CORE, [bad])


def test_unknown_entity_field_rejected() -> None:
    bad = _marketing()
    bad["entities"]["promotions"] = {**bad["entities"]["promotions"], "colours": "red"}
    with pytest.raises(ValidationError):
        build_ontology(CORE, [bad])


def test_dangling_join_side_rejected() -> None:
    bad = _marketing()
    bad["joins"] = [dict(bad["joins"][0], base="merchant_orders")]  # trading 域实体,批〇 未声明
    with pytest.raises(ValueError, match="悬空引用"):
        build_ontology(CORE, [bad])


def test_join_condition_missing_alias_rejected() -> None:
    bad = _marketing()
    bad["joins"] = [dict(bad["joins"][0], condition="p.id = 1")]
    with pytest.raises(ValueError, match="两侧别名"):
        build_ontology(CORE, [bad])


def test_join_bad_type_rejected() -> None:
    bad = _marketing()
    bad["joins"] = [dict(bad["joins"][0], type="outer")]
    with pytest.raises(ValueError, match="type 必须"):
        build_ontology(CORE, [bad])


def test_dimension_dangling_entity_rejected() -> None:
    bad = _marketing()
    bad["dimensions"] = {"promo2": {**bad["dimensions"]["promotion"], "entity": "coupons"}}
    with pytest.raises(ValueError, match="悬空实体引用"):
        build_ontology(CORE, [bad])


def test_entity_dimension_missing_columns_pair_rejected() -> None:
    bad = _marketing()
    bad["dimensions"] = {"promotion": {**bad["dimensions"]["promotion"], "label_column": None}}
    with pytest.raises(ValueError, match="id_column/label_column"):
        build_ontology(CORE, [bad])


def test_alias_conflict_across_domains_rejected() -> None:
    other = _marketing(domain="trading")
    other["entities"] = {
        "merchant_orders": {
            "table": "merchant_orders",
            "database": "merchant_db",
            "alias": "p",  # 与 promotions 冲突
            "label": "订单",
            "columns": {"order_id": "订单号"},
        }
    }
    other["joins"] = []
    other["dimensions"] = {}
    with pytest.raises(ValueError, match="别名.*冲突"):
        build_ontology(CORE, [_marketing(), other])


def test_duplicate_domain_rejected() -> None:
    with pytest.raises(ValueError, match="重复声明"):
        build_ontology(CORE, [_marketing(), _marketing()])


def test_core_version_rejected() -> None:
    with pytest.raises(ValueError, match="不支持的版本"):
        build_core({"version": 2, "domains": [], "databases": [], "faces": []})


def test_core_duplicate_keys_rejected() -> None:
    core = {
        "version": 1,
        "domains": [{"key": "marketing", "label": "a"}, {"key": "marketing", "label": "b"}],
        "databases": [{"key": "merchant_db", "label": "x"}],
        "faces": [{"key": "customer", "label": "y"}],
    }
    with pytest.raises(ValueError, match="键重复"):
        build_core(core)
