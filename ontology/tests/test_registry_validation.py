"""校验负例册:坏声明必须响亮失败(进程起不来),不静默跳过 —— 与
engine semantic_model.py / metric_registry.py 同纪律。

全部用例直接喂 build_ontology / build_application 纯函数坏数据,零文件系统依赖。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ontology import CORE, build_application, build_core, build_ontology

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

ACTIONS_YAML: dict = {
    "version": 1,
    "actions": {
        "approve": {
            "label": "审批通过",
            "faces": ["customer", "staff_review", "spi"],
            "permission": "live_desk:approve",
            "roles": ["platform_admin", "merchant_operator"],
            "requires_approval_id": True,
            "notes": "",
        }
    },
    "ts_ghost_actions": ["reply"],
    "defaults": {"refund_auto_approval_limit": 50.0},
}


def _marketing(**overrides) -> dict:
    data = {
        k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v))
        for k, v in MARKETING_YAML.items()
    }
    data.update(overrides)
    return data


def _trading(alias_c: str = "c") -> dict:
    return {
        "version": 1,
        "domain": "trading",
        "entities": {
            "merchant_orders": {
                "table": "merchant_orders",
                "database": "merchant_db",
                "alias": "o",
                "label": "订单",
                "columns": {"order_id": "订单号"},
            },
            "merchant_customers": {
                "table": "merchant_customers",
                "database": "merchant_db",
                "alias": alias_c,
                "label": "客户",
                "columns": {"customer_id": "客户编号"},
            },
        },
        "joins": [
            {
                "name": "orders_of_customer",
                "table": "merchant_customers",
                "base": "merchant_orders",
                "type": "inner",
                "condition": "c.customer_id = o.customer_id",
            }
        ],
        "dimensions": {},
    }


# --- 域构建 -----------------------------------------------------------------

def test_baseline_build_passes() -> None:
    bundles = build_ontology(CORE, [_marketing()])
    assert "marketing" in bundles


def test_cross_domain_join_resolves_globally() -> None:
    """批一机制:join 声明在 base 侧域文件,table 跨域引用经全域实体表解析。"""
    marketing = _marketing()
    marketing["joins"].append(
        {
            "name": "redemption_of_order",
            "table": "merchant_orders",   # trading 域实体,声明在另一文件
            "base": "promotion_redemptions",
            "type": "inner",
            "condition": "o.order_id = rd.order_id",
        }
    )
    bundles = build_ontology(CORE, [marketing, _trading()])
    names = {j.name for j in bundles["marketing"].joins}
    assert "redemption_of_order" in names


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
    bad["joins"] = [dict(bad["joins"][0], base="no_such_entity")]
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


def test_join_name_duplicate_across_domains_rejected() -> None:
    marketing = _marketing()
    trading = _trading(alias_c="x")
    trading["joins"][0]["name"] = "redemption_of_promotion"   # 与 marketing 撞名
    with pytest.raises(ValueError, match="join 名.*重复"):
        build_ontology(CORE, [marketing, trading])


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


def test_expression_dimension_single_colon_rejected() -> None:
    bad = _marketing()
    bad["dimensions"] = {
        "bad_region": {
            "label": "坏表达式",
            "kind": "expression",
            "entity": "promotions",
            "description": "含单冒号",
            "expression": "substring(p.name from '(?:自治区')",
        }
    }
    with pytest.raises(ValueError, match="单冒号"):
        build_ontology(CORE, [bad])


def test_alias_conflict_across_domains_rejected() -> None:
    with pytest.raises(ValueError, match="别名.*冲突"):
        build_ontology(CORE, [_marketing(), _trading(alias_c="p")])   # p 与 promotions 冲突


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


# --- 动作面构建 --------------------------------------------------------------

def test_application_baseline_passes() -> None:
    app = build_application(CORE, ACTIONS_YAML)
    assert "approve" in app.actions


def test_application_unknown_face_rejected() -> None:
    bad = {
        **ACTIONS_YAML,
        "actions": {"approve": {**ACTIONS_YAML["actions"]["approve"], "faces": ["webhook"]}},
    }
    with pytest.raises(ValueError, match="未知面"):
        build_application(CORE, bad)


def test_application_empty_faces_rejected() -> None:
    bad = {
        **ACTIONS_YAML,
        "actions": {"approve": {**ACTIONS_YAML["actions"]["approve"], "faces": []}},
    }
    with pytest.raises(ValueError, match="faces 不允许为空"):
        build_application(CORE, bad)


def test_application_empty_roles_rejected() -> None:
    bad = {
        **ACTIONS_YAML,
        "actions": {"approve": {**ACTIONS_YAML["actions"]["approve"], "roles": []}},
    }
    with pytest.raises(ValueError, match="roles 白名为空"):
        build_application(CORE, bad)


def test_application_ghost_overlap_rejected() -> None:
    bad = {**ACTIONS_YAML, "ts_ghost_actions": ["reply", "approve"]}
    with pytest.raises(ValueError, match="重叠"):
        build_application(CORE, bad)


def test_application_bad_version_rejected() -> None:
    with pytest.raises(ValueError, match="不支持的版本"):
        build_application(CORE, {**ACTIONS_YAML, "version": 3})
