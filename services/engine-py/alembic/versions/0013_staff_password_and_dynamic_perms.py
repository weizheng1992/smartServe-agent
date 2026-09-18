"""0013 — 员工密码登录 + 按钮权限动态化的种子面修正(JWT 身份收口)。

- staff_members.password_hash:员工自有登录凭证(bcrypt;NULL=仅平台账号可登录),
  网关 /api/admin/analytics/* 从"信任 x-user-id 头"改为"解析 Bearer JWT 的 email
  claim → staff_members",员工各自真实登录。
- role_menus 种子修正:按钮权限点改为由 role_menus 动态派生(勾选即生效)后,
  对存量库删除与原硬编码 _perms() 不符的行,保证升级前后默认权限面等效:
  sales_viewer 剔除 商品编辑/发货/系统管理按钮,warehouse_operator 剔除报告按钮
  (报告生成/导出向来做角色闸,种子给了也没生效)。

幂等:列已存在时跳过;删除按条件执行,行不存在即无操作。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0013_staff_pwd_dyn_perms"
down_revision = "0012_rbac_and_reports"
branch_labels = None
depends_on = None


def _has(conn, table: str) -> bool:
    return conn.dialect.has_table(conn, table)


def _has_column(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in sa.inspect(conn).get_columns(table))


# 与 rbac.DEFAULT_ROLE_MENUS 的 0013 修正保持一致(存量库种子行清理)
_SALES_DENY = ("btn-prod-edit", "btn-order-ship", "btn-menu-create", "btn-role-assign", "btn-staff-invite")
_WH_DENY = ("btn-report-gen", "btn-report-csv")


def upgrade() -> None:
    conn = op.get_bind()

    if _has(conn, "staff_members") and not _has_column(conn, "staff_members", "password_hash"):
        op.add_column("staff_members", sa.Column("password_hash", sa.Text(), nullable=True))

    if _has(conn, "role_menus"):
        op.execute(
            "DELETE FROM role_menus WHERE role = 'sales_viewer' AND menu_id IN "
            "('btn-prod-edit', 'btn-order-ship', 'btn-menu-create', 'btn-role-assign', 'btn-staff-invite')"
        )
        op.execute(
            "DELETE FROM role_menus WHERE role = 'warehouse_operator' AND menu_id IN "
            "('btn-report-gen', 'btn-report-csv')"
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _has(conn, "staff_members") and _has_column(conn, "staff_members", "password_hash"):
        op.drop_column("staff_members", "password_hash")
    # role_menus 种子行不回补:角色管理页可随时重新勾选
