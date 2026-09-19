"""0014 — 售后审批菜单并入客服工作台(菜单信息架构收敛)。

「售后审批」不再独立成菜单:待办审核(HITL 队列)在「客服工作台」页内
与在线聊天同屏处理。迁移清理存量库的菜单行与角色分配行;新库由
rbac.DEFAULT_MENUS(已剔除 m-approvals)直接建对。

幂等:行不存在即无操作。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_drop_approvals_menu"
down_revision = "0013_staff_pwd_dyn_perms"
branch_labels = None
depends_on = None


def _has(conn, table: str) -> bool:
    return conn.dialect.has_table(conn, table)


def upgrade() -> None:
    conn = op.get_bind()
    if not _has(conn, "menus"):
        return
    op.execute("DELETE FROM role_menus WHERE menu_id = 'm-approvals'")
    op.execute("DELETE FROM menus WHERE id = 'm-approvals'")


def downgrade() -> None:
    # 不回插菜单行:角色管理页可随时自行配置(该页能力即本迁移的逆操作)
    pass
