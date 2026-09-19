"""RBAC 三件套服务(13 号;阶段④):菜单树种子/角色分配/员工解析。

- 默认菜单种子(16 号原型四分组 IA 的数据形态);menus 存库后前端动态渲染。
- 角色三档种子(permissionTag 语义):finance_owner 全量 / sales_viewer 不见
  成本 / warehouse_operator 库存物流面;指标权限按 metric_registry.permissionTag
  派生(登记新指标必须带 tag —— 18 号评测契约)。
- 护栏:老板角色的系统菜单不可移除(防锁死)。
- 0013 收口:按钮权限不再硬编码于网关,统一从 role_menus ⨝ menus.perm_code
  动态派生(perms_for_role),角色管理页勾选即生效;指标权限支持 `metric:`
  前缀权限点自定义,未配置时回落内置三档闭集。
"""

from __future__ import annotations

import os

import bcrypt
from sqlalchemy import delete, select

from ..db import Menu, RoleMenu, StaffMember, get_session

ROLES = ("finance_owner", "sales_viewer", "warehouse_operator")
SYSTEM_MENU_IDS = ("m-analytics", "m-reports", "m-products", "m-orders", "m-customers", "m-promotions", "m-menus", "m-roles", "m-staff")

# 默认菜单树(16 号原型同构;menu_type: directory|menu|button)。
# 0014:售后审批不再独立成菜单 —— 待办审核并入「客服工作台」页内呈现。
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
    {"id": "m-spi-logs", "parent": "d-orders", "name": "接口日志", "type": "menu", "route": "/spi-logs", "sort": 3},
    {"id": "d-users", "parent": None, "name": "用户", "type": "directory", "route": None, "sort": 4},
    {"id": "m-customers", "parent": "d-users", "name": "客户管理", "type": "menu", "route": "/customers", "sort": 1},
    {"id": "m-live-desk", "parent": "d-users", "name": "客服工作台", "type": "menu", "route": "/live-desk", "sort": 2},
    {"id": "d-ops", "parent": None, "name": "运营", "type": "directory", "route": None, "sort": 5},
    {"id": "m-promotions", "parent": "d-ops", "name": "优惠活动", "type": "menu", "route": "/promotions", "sort": 1},
    {"id": "btn-promo-create", "parent": "m-promotions", "name": "新建活动", "type": "button", "perm": "promo:create", "sort": 1},
    {"id": "btn-promo-disable", "parent": "m-promotions", "name": "停用活动", "type": "button", "perm": "promo:disable", "sort": 2},
    {"id": "btn-promo-redeem", "parent": "m-promotions", "name": "核销", "type": "button", "perm": "promo:redeem", "sort": 3},
    {"id": "d-system", "parent": None, "name": "系统", "type": "directory", "route": None, "sort": 9},
    {"id": "m-menus", "parent": "d-system", "name": "菜单管理", "type": "menu", "route": "/menus", "sort": 1},
    {"id": "btn-menu-create", "parent": "m-menus", "name": "新增", "type": "button", "perm": "menu:create", "sort": 1},
    {"id": "m-roles", "parent": "d-system", "name": "角色管理", "type": "menu", "route": "/roles", "sort": 2},
    {"id": "btn-role-assign", "parent": "m-roles", "name": "分配权限/保存", "type": "button", "perm": "role:assign", "sort": 1},
    {"id": "m-staff", "parent": "d-system", "name": "员工管理", "type": "menu", "route": "/staff", "sort": 3},
    {"id": "btn-staff-invite", "parent": "m-staff", "name": "邀请员工", "type": "button", "perm": "staff:invite", "sort": 1},
]

# 角色→菜单种子(13-D1;finance_owner=全量,sales_viewer=全量菜单但指标受限,
# warehouse_operator=数据/订单/系统)。按钮节点即接口权限点(0013 动态化后语义
# 为真):种子面与原硬编码 _perms() 等效 —— 运营无商品编辑/发货/系统管理,
# 仓储无报告生成/导出。
_SALES_DENY_BUTTONS = {"btn-prod-edit", "btn-order-ship", "btn-menu-create", "btn-role-assign", "btn-staff-invite"}
DEFAULT_ROLE_MENUS: dict[str, list[str]] = {
    "finance_owner": [m["id"] for m in DEFAULT_MENUS],
    "sales_viewer": [m["id"] for m in DEFAULT_MENUS if m["id"] not in _SALES_DENY_BUTTONS],
    "warehouse_operator": [
        "d-data", "m-analytics", "m-reports",
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


def seed_password_hash() -> str:
    """种子员工登录凭证(0013):与 users 表种子同一环境变量口子,E2E 可覆写。"""
    return bcrypt.hashpw(
        os.environ.get("E2E_ACCOUNT_PASSWORD", "agent-all-dev").encode(), bcrypt.gensalt()
    ).decode()


async def ensure_defaults(business_id: str) -> None:
    """种子幂等:菜单树/角色分配/三档员工账号(员工补密码,可真实登录)。"""
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
        # 三档种子员工(13-D1 默认起步;email 变更后旧行按 id 幂等迁移;
        # 0013 起补 password_hash —— 仅对缺失行算一次 bcrypt,已有值不覆写)
        pwd_hash: str | None = None
        for sid, email, name, role in (
            ("staff_owner", "test@example.com", "老板", "finance_owner"),
            ("staff_ops", "ops@aurora", "运营", "sales_viewer"),
            ("staff_wh", "wh@aurora", "仓储", "warehouse_operator"),
        ):
            if sid in existing_ids:
                row = next(s for s in rows if s.id == sid)
                if row.email != email:
                    row.email, row.display_name, row.role = email, name, role
                if not row.password_hash:
                    pwd_hash = pwd_hash or seed_password_hash()
                    row.password_hash = pwd_hash
            elif email not in existing_emails:
                pwd_hash = pwd_hash or seed_password_hash()
                session.add(StaffMember(
                    id=sid, business_id=business_id, email=email,
                    display_name=name, role=role, status="enabled", password_hash=pwd_hash,
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


async def find_staff(business_id: str, staff_id_or_email: str | None) -> StaffMember | None:
    """员工精确解析(id 或 email);不存在/未识别返回 None(0013 收口:不再
    fail-open 回落 finance_owner —— 冒充他人身份的口子随 x-user-id 信任一起拆除)。"""
    if not staff_id_or_email:
        return None
    async with get_session() as session:
        return (
            await session.execute(
                select(StaffMember).where(
                    StaffMember.business_id == business_id,
                    (StaffMember.id == staff_id_or_email) | (StaffMember.email == staff_id_or_email),
                )
            )
        ).scalars().first()


async def perms_for_role(role: str) -> list[str]:
    """角色 → 按钮权限点闭集(role_menus ⨝ menus.perm_code;0013 动态化,
    角色管理页勾选即生效)。finance_owner 兜底全量已登记权限点。"""
    async with get_session() as session:
        if role == "finance_owner":
            rows = (
                await session.execute(
                    select(Menu.perm_code).where(Menu.menu_type == "button", Menu.perm_code.is_not(None))
                )
            ).scalars().all()
        else:
            rows = (
                await session.execute(
                    select(Menu.perm_code)
                    .join(RoleMenu, RoleMenu.menu_id == Menu.id)
                    .where(RoleMenu.role == role, Menu.menu_type == "button", Menu.perm_code.is_not(None))
                )
            ).scalars().all()
    return sorted(set(rows))


async def set_role_menus(business_id: str, role: str, menu_ids: list[str], operator: str = "system") -> None:
    """保存角色分配(保存即生效);护栏:老板系统菜单强制回补;变更落商户审计。

    父链补齐(实测缺陷修复):勾选深层菜单(如 d-ops/m-promotions)时自动
    补齐其全部祖先目录 —— 否则菜单树从根遍历断链,勾了也不可见。
    """
    if role == "finance_owner":
        menu_ids = list({*menu_ids, *SYSTEM_MENU_IDS})
    async with get_session() as session:
        all_menus = (await session.execute(select(Menu))).scalars().all()
        by_id = {m.id: m for m in all_menus}
        expanded: set[str] = set()
        stack = [mid for mid in menu_ids if mid in by_id]
        while stack:
            mid = stack.pop()
            if mid in expanded:
                continue
            expanded.add(mid)
            parent_id = by_id[mid].parent_id
            if parent_id and parent_id not in expanded:
                stack.append(parent_id)
        await session.execute(delete(RoleMenu).where(RoleMenu.role == role))
        for mid in sorted(expanded):
            session.add(RoleMenu(role=role, menu_id=mid, business_id=business_id))
        await session.commit()
    try:  # 审计(20-D5):失败打印不阻断(与写穿透同策略)

        from .promotions import _audit

        await _audit("rbac_role_menus", operator, {"role": role, "menuIds": menu_ids, "businessId": business_id})
    except Exception as err:
        print(f"[RBAC] audit failed: {err}")


async def allowed_metrics_for_role(role: str) -> list[str] | None:
    """指标闭集过滤(13-D2;None=全量)。

    0013 起两级解析:角色若持有 `metric:` 前缀按钮权限点(菜单管理可自行
    登记,如 metric:gmv),以权限点为准;未配置任何 metric: 点时回落内置
    三档闭集(自定义角色默认按运营口径,成本类仍不可见)。
    """
    if role == "finance_owner":
        return None
    metric_perms = {p.removeprefix("metric:") for p in await perms_for_role(role) if p.startswith("metric:")}
    if metric_perms:
        return sorted(metric_perms)
    return ROLE_METRIC_PERMISSIONS.get(role, ROLE_METRIC_PERMISSIONS["sales_viewer"])
