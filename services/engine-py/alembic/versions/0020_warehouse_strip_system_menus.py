"""0020 — warehouse_operator 种子面收敛:剔除系统管理三件套。

rbac.DEFAULT_ROLE_MENUS 的仓储面收敛为 数据/订单(2026-10-10 用户裁决):
菜单/角色/员工管理及其按钮(menu:create/role:assign/staff:invite)为老板专属。
变更类接口本就有 is_manager 硬闸(POST /roles、POST /roles/{role}/menus 等),
种子放行只会产出「看得到、点不动」的 403 体验与配置面信息泄漏。

幂等:ensure_menu_seed 只增不删,收敛必须配存量库清理(0013 先例);
按 role + menu_id 条件删除,行不存在即无操作。非 aurora 租户的种子行
带 ":business_id" 后缀,一并覆盖。

downgrade 不回补:角色管理页可随时重新勾选(同 0013 语义)。
"""

import sqlalchemy as sa
from sqlalchemy import bindparam

from alembic import op

revision = "0020_wh_strip_system_menus"
down_revision = "0019_staff_dept_level"
branch_labels = None
depends_on = None

# 与 rbac.DEFAULT_ROLE_MENUS 的 0020 修正保持一致(存量库种子行清理)
_WH_SYSTEM_MENU_IDS = (
    "d-system",
    "m-menus",
    "btn-menu-create",
    "m-roles",
    "btn-role-assign",
    "m-staff",
    "btn-staff-invite",
)


def upgrade() -> None:
    conn = op.get_bind()
    if not conn.dialect.has_table(conn, "role_menus"):
        return
    # id 作参数值而非 SQL 文本:menu_id 可能带 ":business_id" 后缀,裸拼字面量会
    # 被 text() 当绑定占位符(实弹教训);expanding IN 承接裸 id + 后缀变体
    targets = [*_WH_SYSTEM_MENU_IDS, *(f":{mid}" for mid in _WH_SYSTEM_MENU_IDS)]
    conn.execute(
        sa.text(
            "DELETE FROM role_menus WHERE role = 'warehouse_operator' "
            "AND menu_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": targets},
    )


def downgrade() -> None:
    # 种子行不回补:角色管理页可随时重新勾选(同 0013)
    pass
