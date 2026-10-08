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

ROLES = ("finance_owner", "admin", "sales_viewer", "warehouse_operator", "support_agent")
# 管理角色:可分配权限/管理系统配置(老板+管理员);老板额外保留防锁死护栏
MANAGER_ROLES = ("finance_owner", "admin")
SYSTEM_MENU_IDS = ("m-analytics", "m-reports", "m-board", "m-products", "m-orders", "m-customers", "m-promotions", "m-menus", "m-roles", "m-staff", "m-agent-desk")

# 「该找谁」责任人路由种子组织(spec .scratch/owner-routing):店长 1 + 五部门
# 主管/专员。员工本体即责任人(Q7 裁决:复用 staff_members,不建第二套人名册);
# dept/level 是人事属性(0019 列),不参与 RBAC 判定。id 固定 —— gateway
# merchant_seed 灌 owner_mappings/promotions.created_by/spus.owner_id 时以本册
# 为唯一 id 事实源(跨库无 FK,互验闸兜底)。前四行是历史三档种子,id/email
# 冻结不可改(契约与既有库数据依赖)。
STAFF_SEED_ROSTER: tuple[tuple[str, str, str, str, str | None, str | None], ...] = (
    # (id, email, display_name, role, dept, level)
    ("staff_owner", "test@example.com", "老板", "finance_owner", None, "店长"),
    ("staff_admin", "admin@aurora", "管理员", "admin", None, None),
    ("staff_ops", "ops@aurora", "运营", "sales_viewer", "运营部", "专员"),
    ("staff_wh", "wh@aurora", "仓储", "warehouse_operator", "仓储部", "专员"),
    ("staff_sales_lead", "sales_lead@aurora", "陈锋", "sales_viewer", "销售部", "主管"),
    ("staff_sales_1", "sales1@aurora", "李芸", "sales_viewer", "销售部", "专员"),
    ("staff_sales_2", "sales2@aurora", "赵磊", "sales_viewer", "销售部", "专员"),
    ("staff_ops_lead", "ops_lead@aurora", "周婷", "sales_viewer", "运营部", "主管"),
    ("staff_aftersale_lead", "as_lead@aurora", "吴敏", "support_agent", "售后部", "主管"),
    ("staff_aftersale_1", "as1@aurora", "郑浩", "support_agent", "售后部", "专员"),
    ("staff_finance_lead", "fin_lead@aurora", "孙洁", "finance_owner", "财务部", "主管"),
    ("staff_wh_lead", "wh_lead@aurora", "何强", "warehouse_operator", "仓储部", "主管"),
)

# 默认菜单树(16 号原型同构;menu_type: directory|menu|button)。
# 0014:售后审批不再独立成菜单 —— 待办审核并入「客服工作台」页内呈现。
DEFAULT_MENUS: list[dict] = [
    {"id": "d-data", "parent": None, "name": "数据", "type": "directory", "route": None, "sort": 1},
    {"id": "m-analytics", "parent": "d-data", "name": "数据分析", "type": "menu", "route": "/analytics", "sort": 1},
    {"id": "btn-report-gen", "parent": "m-analytics", "name": "生成报告", "type": "button", "perm": "report:gen", "sort": 1},
    {"id": "btn-report-csv", "parent": "m-analytics", "name": "导出 CSV", "type": "button", "perm": "report:csv", "sort": 2},
    {"id": "m-reports", "parent": "d-data", "name": "我的报告", "type": "menu", "route": "/reports", "sort": 2},
    {"id": "m-board", "parent": "d-data", "name": "数据看板", "type": "menu", "route": "/board", "sort": 3},
    # 「该找谁」责任人路由(spec .scratch/owner-routing §5):映射维护页 ——
    # 编辑走老板/管理员闸(接口侧),菜单仅可见性;仓储角色子集不含即不可见。
    {"id": "m-owner-mappings", "parent": "d-data", "name": "责任人维护", "type": "menu", "route": "/owner-mappings", "sort": 4},
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
    # 02 安全先行(2026-09-27):工作台此前整菜单无任何权限点,按钮级收口无词可查
    # (perm 闭包只认 button 型子节点)。占位编码 live_desk:operate,种子面与菜单
    # 可见性对齐(老板/管理员/运营可见即持有,仓储无此菜单);坐席身份模型定档后
    # (live-desk 地图)再细化坐席专属角色与拆分接单/接管粒度。
    {"id": "btn-live-desk-operate", "parent": "m-live-desk", "name": "坐席操作", "type": "button", "perm": "live_desk:operate", "sort": 1},
    # live-desk-rework P4(spec §2.6):工单批驳一等权限点 —— 台内嵌批驳卡与
    # 员工代行 approve/reject(/api/chat/approvals)都过此闸;退款核准是资金
    # 语义,与接单/发言(live_desk:operate)分粒度,不放给无批驳权限的坐席。
    {"id": "btn-live-desk-approve", "parent": "m-live-desk", "name": "工单批驳", "type": "button", "perm": "live_desk:approve", "sort": 2},
    # live-desk-rework P2(spec §3 灰度):新坐席台独立页 —— 灰度开关就是本菜单的
    # 角色可见性,零新 env。先只授老板/管理员(sales_viewer 种子排除,见
    # _GREY_RELEASE_MENUS);support_agent 稳后放;旧 /live-desk tab 并存至 P5 退役。
    {"id": "m-agent-desk", "parent": "d-users", "name": "坐席工作台", "type": "menu", "route": "/agent-desk", "sort": 3},
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
# 灰度中菜单(live-desk-rework §3):运营暂不可见,稳后并入其种子面
_GREY_RELEASE_MENUS = {"m-agent-desk"}
DEFAULT_ROLE_MENUS: dict[str, list[str]] = {
    "finance_owner": [m["id"] for m in DEFAULT_MENUS],
    "admin": [m["id"] for m in DEFAULT_MENUS],
    "sales_viewer": [m["id"] for m in DEFAULT_MENUS if m["id"] not in _SALES_DENY_BUTTONS and m["id"] not in _GREY_RELEASE_MENUS],
    "warehouse_operator": [
        "d-data", "m-analytics", "m-reports", "m-board",
        "d-orders", "m-orders", "btn-order-ship", "m-spi-logs",
        "d-system", "m-menus", "btn-menu-create", "m-roles", "btn-role-assign", "m-staff", "btn-staff-invite",
    ],
    # live-desk-rework §2.2:专职客服 = 客服工作台 + 客户管理,不给数据分析/
    # 订单/商品/优惠/系统面(商户招客服不泄经营数据);新坐席台按灰度暂不授。
    # P4:客服本职含工单批驳(btn-live-desk-approve,live_desk:approve)。
    "support_agent": [
        "d-users", "m-customers", "m-live-desk", "btn-live-desk-operate", "btn-live-desk-approve",
    ],
}

# 角色→指标可见闭集(13-D2:成本敏感三指标限 finance_owner;仓储见库存面)
ROLE_METRIC_PERMISSIONS: dict[str, list[str] | None] = {
    "finance_owner": None,  # None = 全量
    "admin": None,  # 管理员同老板全量
    "sales_viewer": ["gmv", "net_sales", "gmv_trend", "volume_trend", "orders_trend", "order_overview", "volume", "review_bad", "review_good", "refund_rate", "session_volume", "ai_resolution_rate", "aov", "order_count", "zero_sales", "category_gmv_top", "customer_spend_top", "customer_spend_stats", "customer_coupons", "customer_profile", "customer_panorama", "customer_spend_trend", "biz_overview", "gmv_mom", "attribution_refund", "attribution_sales", "spu_compare"],
    "warehouse_operator": ["volume", "stock_risk", "refund_rate", "session_volume", "zero_sales", "stock_value", "orders_trend"],
}


def is_manager(role: str) -> bool:
    """管理角色(老板/管理员):可分配权限、管理系统配置。"""
    return role in MANAGER_ROLES


def seed_password_hash() -> str:
    """种子员工登录凭证(0013):与 users 表种子同一环境变量口子,E2E 可覆写。"""
    return bcrypt.hashpw(
        os.environ.get("E2E_ACCOUNT_PASSWORD", "agent-all-dev").encode(), bcrypt.gensalt()
    ).decode()


async def ensure_menu_seed(business_id: str) -> None:
    """菜单树 + 角色分配种子(幂等)。从 ensure_defaults 拆出:测试基建可单独
    为任意租户补菜单面(如 realtime 契约的 nike 坐席需持 live_desk:operate),
    不触碰员工种子(员工 id 固定,跨租户直插会撞主键)。

    id 策略(live-desk P2 实测教训):``menus.id`` 是**全局唯一**主键而
    business_id 只是普通列 —— 裸 id 双租户必撞(谁先种谁赢,第二家
    UniqueViolationError)。aurora 作为冻结契约与 dev 的既定租户保持历史裸 id;
    其余租户一律 ``{id}:{business_id}`` 后缀隔离(parent 链同步后缀),
    perm_code 不变,角色闭包查询按 business_id 过滤后语义等同。"""
    suffix = "" if business_id == "aurora" else f":{business_id}"
    async with get_session() as session:
        existing = {
            m.id for m in
            (await session.execute(select(Menu).where(Menu.business_id == business_id))).scalars()
        }
        for m in DEFAULT_MENUS:
            mid = m["id"] + suffix
            if mid not in existing:
                session.add(Menu(
                    id=mid, business_id=business_id,
                    parent_id=(m["parent"] + suffix) if m.get("parent") else None,
                    name=m["name"], menu_type=m["type"], route=m.get("route"), perm_code=m.get("perm"),
                    sort_order=m.get("sort", 0), status="enabled",
                ))
        existing_rm = {
            (rm.role, rm.menu_id) for rm in
            (await session.execute(select(RoleMenu).where(RoleMenu.business_id == business_id))).scalars()
        }
        for role, menu_ids in DEFAULT_ROLE_MENUS.items():
            for mid in menu_ids:
                rid = mid + suffix
                if (role, rid) not in existing_rm:
                    session.add(RoleMenu(role=role, menu_id=rid, business_id=business_id))
        await session.commit()


async def ensure_defaults(business_id: str) -> None:
    """种子幂等:菜单树/角色分配/三档员工账号(员工补密码,可真实登录)。"""
    await ensure_menu_seed(business_id)
    async with get_session() as session:
        rows = (
            await session.execute(select(StaffMember).where(StaffMember.business_id == business_id))
        ).scalars().all()
        existing_ids = {s.id for s in rows}
        existing_emails = {s.email for s in rows}
        # 种子组织(STAFF_SEED_ROSTER 单一事实源;历史三档在前四行,email 变更后
        # 旧行按 id 幂等迁移;0013 起补 password_hash —— 仅对缺失行算一次 bcrypt,
        # 已有值不覆写;0019 起带 dept/level 人事属性)
        pwd_hash: str | None = None
        for sid, email, name, role, dept, level in STAFF_SEED_ROSTER:
            if sid in existing_ids:
                row = next(s for s in rows if s.id == sid)
                if row.email != email:
                    row.email, row.display_name, row.role = email, name, role
                if row.dept != dept:
                    row.dept = dept
                if row.level != level:
                    row.level = level
                if not row.password_hash:
                    pwd_hash = pwd_hash or seed_password_hash()
                    row.password_hash = pwd_hash
            elif email not in existing_emails:
                pwd_hash = pwd_hash or seed_password_hash()
                session.add(StaffMember(
                    id=sid, business_id=business_id, email=email,
                    display_name=name, role=role, status="enabled", password_hash=pwd_hash,
                    dept=dept, level=level,
                ))
        await session.commit()


async def menu_tree_for_role(business_id: str, role: str) -> list[dict]:
    """角色可见菜单树(服务端强制;前端仅为呈现)。目录折叠:父目录保留当且仅当
    有可见子项。"""
    async with get_session() as session:
        menus = (
            await session.execute(
                select(Menu).where(Menu.status == "enabled", Menu.business_id == business_id)
            )
        ).scalars().all()
        allowed = {
            rm.menu_id for rm in
            (await session.execute(
                select(RoleMenu).where(RoleMenu.role == role, RoleMenu.business_id == business_id)
            )).scalars()
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


async def perms_for_role(business_id: str, role: str) -> list[str]:
    """角色 → 按钮权限点闭集(role_menus ⨝ menus.perm_code;0013 动态化,
    角色管理页勾选即生效)。finance_owner 兜底全量已登记权限点。"""
    async with get_session() as session:
        if role == "finance_owner":
            rows = (
                await session.execute(
                    select(Menu.perm_code).where(
                        Menu.menu_type == "button", Menu.perm_code.is_not(None),
                        Menu.business_id == business_id,
                    )
                )
            ).scalars().all()
        else:
            rows = (
                await session.execute(
                    select(Menu.perm_code)
                    .join(RoleMenu, RoleMenu.menu_id == Menu.id)
                    .where(
                        RoleMenu.role == role, Menu.menu_type == "button",
                        Menu.perm_code.is_not(None), Menu.business_id == business_id,
                    )
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
        all_menus = (
            await session.execute(select(Menu).where(Menu.business_id == business_id))
        ).scalars().all()
        by_id = {m.id: m for m in all_menus}
        # 传入 id 全部保留(静默丢弃会让「勾了却不生效」);父链只为存在者补祖先
        expanded: set[str] = set(menu_ids)
        unknown = [mid for mid in menu_ids if mid not in by_id]
        if unknown:
            print(f"[RBAC] 警告: menu_ids 含未登记菜单(已原样保留): {unknown}")
        stack = [mid for mid in menu_ids if mid in by_id]
        while stack:
            mid = stack.pop()
            parent_id = by_id[mid].parent_id
            if parent_id and parent_id not in expanded:
                expanded.add(parent_id)
                stack.append(parent_id)
        await session.execute(
            delete(RoleMenu).where(
                RoleMenu.role == role, RoleMenu.business_id == business_id
            )
        )
        for mid in sorted(expanded):
            session.add(RoleMenu(role=role, menu_id=mid, business_id=business_id))
        await session.commit()
    try:  # 审计(20-D5):失败打印不阻断(与写穿透同策略)

        from .promotions import audit

        await audit("rbac_role_menus", operator, {"role": role, "menuIds": menu_ids, "businessId": business_id})
    except Exception as err:
        print(f"[RBAC] audit failed: {err}")


async def allowed_metrics_for_role(business_id: str, role: str) -> list[str] | None:
    """指标闭集过滤(13-D2;None=全量)。

    0013 起两级解析:角色若持有 `metric:` 前缀按钮权限点(菜单管理可自行
    登记,如 metric:gmv),以权限点为准;未配置任何 metric: 点时回落内置
    三档闭集(自定义角色默认按运营口径,成本类仍不可见)。
    """
    if role == "finance_owner":
        return None
    metric_perms = {
        p.removeprefix("metric:")
        for p in await perms_for_role(business_id, role) if p.startswith("metric:")
    }
    if metric_perms:
        return sorted(metric_perms)
    return ROLE_METRIC_PERMISSIONS.get(role, ROLE_METRIC_PERMISSIONS["sales_viewer"])
