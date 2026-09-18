"""RBAC 三件套服务(13 号;阶段④):菜单树种子/角色分配/员工解析。

- 默认菜单种子(16 号原型四分组 IA 的数据形态);menus 存库后前端动态渲染。
- 角色三档种子(permissionTag 语义):finance_owner 全量 / sales_viewer 不见
  成本 / warehouse_operator 库存物流面;指标权限按 metric_registry.permissionTag
  派生(登记新指标必须带 tag —— 18 号评测契约)。
- 护栏:老板角色的系统菜单不可移除(防锁死)。
"""

from __future__ import annotations

from sqlalchemy import delete, select

from ..db import Menu, RoleMenu, StaffMember, get_session

ROLES = ("finance_owner", "sales_viewer", "warehouse_operator")
SYSTEM_MENU_IDS = ("m-analytics", "m-reports", "m-products", "m-orders", "m-customers", "m-promotions", "m-menus", "m-roles", "m-staff")

# 默认菜单树(16 号原型同构;menu_type: directory|menu|button)
DEFAULT_MENUS: list[dict] = [
    {"id": "d-data", "parent": None, "name": "数据", "type": "directory", "route": None, "sort": 1},
    {"id": "m-analytics", "parent": "d-data", "name": "数据分析", "type": "menu", "route": "/analytics", "sort": 1},
    {"id": "btn-report-gen", "parent": "m-analytics", "name": "生成报告", "type": "button", "perm": "report:gen", "sort": 1},
    {"id": "btn-report-csv", "parent": "m-analytics", "name": "导出 CSV", "type": "button", "perm": "report:csv", "sort": 2},
    {"id": "m-reports", "parent": "d-data", "name": "我的报告", "type": "menu", "route": "/reports", "sort": 2},
    {"id": "d-goods", "parent": None, "name": "商品", "type": "directory", "route": None, "sort": 2},
    {"id": "m-products", "parent": "d-goods", "name": "商品列表", "type": "menu", "route": "/products", "sort": 1},
    {"id": "btn-prod-edit", "parent": "m-products", "name": "商品编辑/上下架", "type": "button", "perm": "prod:edit", "sort": 1},
    {"id": "m-skus", "parent": "d-goods", "name": "SKU 库存", "type": "menu", "route": "/skus", "sort": 2},
    {"id": "d-orders", "parent": None, "name": "订单", "type": "directory", "route": None, "sort": 3},
    {"id": "m-orders", "parent": "d-orders", "name": "订单履约", "type": "menu", "route": "/orders", "sort": 1},
    {"id": "btn-order-ship", "parent": "m-orders", "name": "发货操作", "type": "button", "perm": "order:ship", "sort": 1},
    {"id": "m-approvals", "parent": "d-orders", "name": "售后审批", "type": "menu", "route": "/approvals", "sort": 2},
    {"id": "m-spi-logs", "parent": "d-orders", "name": "接口日志", "type": "menu", "route": "/spi-logs", "sort": 3},
    {"id": "d-users", "parent": None, "name": "用户", "type": "directory", "route": None, "sort": 4},
    {"id": "m-customers", "parent": "d-users", "name": "客户管理", "type": "menu", "route": "/customers", "sort": 1},
    {"id": "m-live-desk", "parent": "d-users", "name": "客服工作台", "type": "menu", "route": "/live-desk", "sort": 2},
    {"id": "d-ops", "parent": None, "name": "运营", "type": "directory", "route": None, "sort": 5},
    {"id": "m-promotions", "parent": "d-ops", "name": "优惠活动", "type": "menu", "route": "/promotions", "sort": 1},
    {"id": "btn-promo-create", "parent": "m-promotions", "name": "新建活动", "type": "button", "perm": "promo:create", "sort": 1},
    {"id": "btn-promo-disable", "parent": "m-promotions", "name": "停用活动", "type": "button", "perm": "promo:disable", "sort": 2},
    {"id": "d-system", "parent": None, "name": "系统", "type": "directory", "route": None, "sort": 9},
    {"id": "m-menus", "parent": "d-system", "name": "菜单管理", "type": "menu", "route": "/menus", "sort": 1},
    {"id": "btn-menu-create", "parent": "m-menus", "name": "新增", "type": "button", "perm": "menu:create", "sort": 1},
    {"id": "m-roles", "parent": "d-system", "name": "角色管理", "type": "menu", "route": "/roles", "sort": 2},
    {"id": "btn-role-assign", "parent": "m-roles", "name": "分配权限/保存", "type": "button", "perm": "role:assign", "sort": 1},
    {"id": "m-staff", "parent": "d-system", "name": "员工管理", "type": "menu", "route": "/staff", "sort": 3},
    {"id": "btn-staff-invite", "parent": "m-staff", "name": "邀请员工", "type": "button", "perm": "staff:invite", "sort": 1},
]

# 角色→菜单种子(13-D1;finance_owner=全量,sales_viewer=全量菜单但指标受限,
# warehouse_operator=数据/订单/系统)
DEFAULT_ROLE_MENUS: dict[str, list[str]] = {
    "finance_owner": [m["id"] for m in DEFAULT_MENUS],
    "sales_viewer": [m["id"] for m in DEFAULT_MENUS],
    "warehouse_operator": [
        "d-data", "m-analytics", "btn-report-gen", "btn-report-csv", "m-reports",
        "d-orders", "m-orders", "btn-order-ship", "m-spi-logs",
        "d-system", "m-menus", "btn-menu-create", "m-roles", "btn-role-assign", "m-staff", "btn-staff-invite",
    ],
}

# 角色→指标可见闭集(13-D2:成本敏感三指标限 finance_owner;仓储见库存面)
ROLE_METRIC_PERMISSIONS: dict[str, list[str] | None] = {
    "finance_owner": None,  # None = 全量
    "sales_viewer": ["gmv", "volume", "review_bad", "refund_rate", "session_volume", "ai_resolution_rate"],
    "warehouse_operator": ["volume", "stock_risk", "refund_rate", "session_volume"],
}


async def ensure_defaults(business_id: str) -> None:
    """种子幂等:菜单树/角色分配/老板员工账号(默认全员 finance_owner 起步)。"""
    async with get_session() as session:
        existing = {m.id for m in (await session.execute(select(Menu))).scalars()}
        for m in DEFAULT_MENUS:
            if m["id"] not in existing:
                session.add(Menu(
                    id=m["id"], business_id=business_id, parent_id=m["parent"], name=m["name"],
                    menu_type=m["type"], route=m.get("route"), perm_code=m.get("perm"),
                    sort_order=m.get("sort", 0), status="enabled",
                ))
        existing_rm = {(rm.role, rm.menu_id) for rm in (await session.execute(select(RoleMenu))).scalars()}
        for role, menu_ids in DEFAULT_ROLE_MENUS.items():
            for mid in menu_ids:
                if (role, mid) not in existing_rm:
                    session.add(RoleMenu(role=role, menu_id=mid, business_id=business_id))
        rows = (await session.execute(select(StaffMember))).scalars().all()
        existing_ids = {s.id for s in rows}
        existing_emails = {s.email for s in rows}
        # 三档种子员工(13-D1 默认起步;email 变更后旧行按 id 幂等迁移)
        for sid, email, name, role in (
            ("staff_owner", "test@example.com", "老板", "finance_owner"),
            ("staff_ops", "ops@aurora", "运营", "sales_viewer"),
            ("staff_wh", "wh@aurora", "仓储", "warehouse_operator"),
        ):
            if sid in existing_ids:
                row = next(s for s in rows if s.id == sid)
                if row.email != email:
                    row.email, row.display_name, row.role = email, name, role
            elif email not in existing_emails:
                session.add(StaffMember(
                    id=sid, business_id=business_id, email=email,
                    display_name=name, role=role, status="enabled",
                ))
        await session.commit()


async def menu_tree_for_role(business_id: str, role: str) -> list[dict]:
    """角色可见菜单树(服务端强制;前端仅为呈现)。目录折叠:父目录保留当且仅当
    有可见子项。"""
    async with get_session() as session:
        menus = (await session.execute(select(Menu).where(Menu.status == "enabled"))).scalars().all()
        allowed = {
            rm.menu_id for rm in
            (await session.execute(select(RoleMenu).where(RoleMenu.role == role))).scalars()
        }
    visible = [m for m in menus if m.id in allowed or role == "finance_owner"]
    # 护栏(13 号):老板系统菜单不可移除 —— 即便 role_menus 被清也强制可见
    if role == "finance_owner":
        visible = menus
    tree = []
    for m in sorted([x for x in visible if x.parent_id is None], key=lambda x: x.sort_order):
        tree.append(_menu_node(m, visible))
    # 目录含间接子项的可见性:目录无可见子项且自身非菜单则剔除
    return [n for n in tree if n["menuType"] == "menu" or n["children"]]


def _menu_node(m, visible) -> dict:
    children = sorted([x for x in visible if x.parent_id == m.id], key=lambda x: x.sort_order)
    return {
        "id": m.id, "name": m.name, "menuType": m.menu_type, "route": m.route,
        "permCode": m.perm_code, "sort": m.sort_order,
        "children": [_menu_node(c, visible) for c in children],
    }


async def resolve_staff_role(business_id: str, staff_id_or_email: str | None) -> tuple[str, str]:
    """员工 → (role, display_name);未注册员工默认 finance_owner(13-D1 起步)。"""
    if not staff_id_or_email:
        return "finance_owner", "未识别"
    async with get_session() as session:
        row = (
            await session.execute(
                select(StaffMember).where(
                    StaffMember.business_id == business_id,
                    (StaffMember.id == staff_id_or_email) | (StaffMember.email == staff_id_or_email),
                )
            )
        ).scalars().first()
    if row and row.status == "enabled":
        return row.role, row.display_name
    return "finance_owner", staff_id_or_email


async def set_role_menus(business_id: str, role: str, menu_ids: list[str], operator: str = "system") -> None:
    """保存角色分配(保存即生效);护栏:老板系统菜单强制回补;变更落商户审计。"""
    if role == "finance_owner":
        menu_ids = list({*menu_ids, *SYSTEM_MENU_IDS})
    async with get_session() as session:
        await session.execute(delete(RoleMenu).where(RoleMenu.role == role))
        for mid in menu_ids:
            session.add(RoleMenu(role=role, menu_id=mid, business_id=business_id))
        await session.commit()
    try:  # 审计(20-D5):失败打印不阻断(与写穿透同策略)

        from .promotions import _audit

        await _audit("rbac_role_menus", operator, {"role": role, "menuIds": menu_ids, "businessId": business_id})
    except Exception as err:
        print(f"[RBAC] audit failed: {err}")


def allowed_metrics_for_role(role: str) -> list[str] | None:
    """指标闭集过滤(13-D2;None=全量)。"""
    return ROLE_METRIC_PERMISSIONS.get(role or "finance_owner")
