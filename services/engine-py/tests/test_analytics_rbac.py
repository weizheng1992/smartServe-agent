"""RBAC 纯逻辑单册(2026-10-02 夜审测试补强):种子面完整性与成本敏感指标
闭集的跨工件一致性 —— 全程不触库,DEFAULT_MENUS/DEFAULT_ROLE_MENUS 与
metrics.yaml 是唯一事实源。

此前 analytics/rbac.py 只有 gateway 侧 71 例契约间接覆盖(菜单/角色/员工
三件套走 HTTP 面);种子常量内部的悬空菜单 id、成本指标漏进受限角色闭集、
metrics.yaml 改名后 rbac.py 闭集留死键这类漂移没有任何直接断言。
"""

from __future__ import annotations

import pytest

from engine_py.analytics.rbac import (
    DEFAULT_MENUS,
    DEFAULT_ROLE_MENUS,
    ROLE_METRIC_PERMISSIONS,
    ROLES,
    is_manager,
)
from engine_py.tools_registry.metric_registry import METRIC_SEMANTIC_REGISTRY

_MENU_IDS = {m["id"] for m in DEFAULT_MENUS}
# 成本敏感双指标(metrics.yaml permissionTag=finance_owner 全量仅此两个)
_COST_METRICS = {
    key
    for key, entry in METRIC_SEMANTIC_REGISTRY.items()
    if entry["permissionTag"] == "finance_owner"
}


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("finance_owner", True),
        ("admin", True),
        ("sales_viewer", False),
        ("warehouse_operator", False),
        ("support_agent", False),
        ("unknown_role", False),
    ],
)
def test_is_manager_matrix(role: str, expected: bool):
    assert is_manager(role) is expected


def test_role_seed_keys_are_registered_roles():
    """角色种子键必须都在 ROLES 闭集内(手滑新角色不生效且无人知)。"""
    assert set(DEFAULT_ROLE_MENUS) <= set(ROLES)


@pytest.mark.parametrize("role", sorted(DEFAULT_ROLE_MENUS))
def test_role_menu_ids_all_registered(role: str):
    """悬空菜单 id 会静默产出不可见的 role_menu 行(ensure_menu_seed 只查
    已种菜单,不查 DEFAULT_MENUS)—— 种子引用必须全部登记。"""
    unknown = [mid for mid in DEFAULT_ROLE_MENUS[role] if mid not in _MENU_IDS]
    assert unknown == [], f"{role} 引用了未登记菜单: {unknown}"


def test_sales_viewer_denies_dangerous_buttons_and_grey_desk():
    """运营种子面:商品编辑/发货/系统管理按钮与灰度坐席台不得出现。"""
    ids = set(DEFAULT_ROLE_MENUS["sales_viewer"])
    assert "btn-prod-edit" not in ids
    assert "btn-order-ship" not in ids
    assert "btn-menu-create" not in ids
    assert "btn-role-assign" not in ids
    assert "btn-staff-invite" not in ids
    assert "m-agent-desk" not in ids


def test_warehouse_operator_no_system_face():
    """仓储种子面 = 数据/订单,系统管理三件套(菜单/角色/员工 + 各自按钮)
    一律不可见(2026-10-10 用户裁决):变更类接口本就有 is_manager 硬闸,
    种子面再放行只会产出「看得到、点不动」的 403 体验。"""
    ids = set(DEFAULT_ROLE_MENUS["warehouse_operator"])
    for face in ("d-system", "m-menus", "btn-menu-create", "m-roles", "btn-role-assign", "m-staff", "btn-staff-invite"):
        assert face not in ids
    # 本职面仍在:数据三页 + 订单履约(含发货按钮) + 接口日志
    assert {"d-data", "m-analytics", "m-reports", "m-board", "d-orders", "m-orders", "btn-order-ship", "m-spi-logs"} <= ids


def test_finance_and_admin_seed_full_face():
    for role in ("finance_owner", "admin"):
        assert set(DEFAULT_ROLE_MENUS[role]) == _MENU_IDS


def test_support_agent_no_business_faces():
    """专职客服只见客服工作台+客户管理:经营数据面(数据/商品/订单/运营/系统)
    一律不可见 —— 商户招客服不泄经营数据(live-desk-rework §2.2)。"""
    ids = set(DEFAULT_ROLE_MENUS["support_agent"])
    for face in ("d-data", "m-analytics", "d-goods", "d-orders", "d-ops", "d-system"):
        assert face not in ids
    assert {"m-live-desk", "btn-live-desk-operate", "btn-live-desk-approve"} <= ids


def test_cost_metrics_never_leak_into_limited_roles():
    """成本双指标(gross_profit/margin_rate)只属老板:运营/仓储闭集绝不含。"""
    for role in ("sales_viewer", "warehouse_operator"):
        leaked = _COST_METRICS & set(ROLE_METRIC_PERMISSIONS[role] or [])
        assert leaked == set(), f"{role} 闭集泄漏成本指标: {leaked}"


@pytest.mark.parametrize("role", ["sales_viewer", "warehouse_operator"])
def test_limited_closed_sets_reference_live_metrics(role: str):
    """闭集里的每个指标键都必须在 metrics.yaml 活着 —— 改名/下线指标留死键
    会让该行权限静默失效(等价于闭集缩水)。"""
    stale = [m for m in ROLE_METRIC_PERMISSIONS[role] if m not in METRIC_SEMANTIC_REGISTRY]
    assert stale == [], f"{role} 闭集引用了注册表外指标: {stale}"


def test_manager_roles_have_full_metric_access():
    """老板/管理员闭集为 None(全量语义);受限角色闭集非 None。"""
    assert ROLE_METRIC_PERMISSIONS["finance_owner"] is None
    assert ROLE_METRIC_PERMISSIONS["admin"] is None
    assert ROLE_METRIC_PERMISSIONS["sales_viewer"] is not None
    assert ROLE_METRIC_PERMISSIONS["warehouse_operator"] is not None
