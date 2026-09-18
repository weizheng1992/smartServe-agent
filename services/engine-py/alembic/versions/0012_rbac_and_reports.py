"""0012 — RBAC 三件套 + analytics_reports(wayfinder 13/14/16 号;阶段④⑤)。

- menus:菜单树(目录/菜单/按钮三级;business_id 隔离;前端路由按此动态渲染)
- role_menus:角色↔菜单(含按钮权限点)多对多
- staff_members:员工↔角色(顶栏快捷切换账号读取;13-D1 三档种子)
- analytics_reports:报告产物(14-D4;HTML 内容引用 uploads 通道)
幂等:表已存在时跳过(共享容器二次升级)。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0012_rbac_and_reports"
down_revision = "0011_query_exemplars"
branch_labels = None
depends_on = None


def _has(conn, table: str) -> bool:
    return conn.dialect.has_table(conn, table)


def upgrade() -> None:
    conn = op.get_bind()

    if not _has(conn, "menus"):
        op.create_table(
            "menus",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("business_id", sa.Text(), nullable=False),
            sa.Column("parent_id", sa.Text(), nullable=True),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("menu_type", sa.Text(), nullable=False),  # directory|menu|button
            sa.Column("route", sa.Text(), nullable=True),
            sa.Column("perm_code", sa.Text(), nullable=True),  # 按钮权限点 perms:xxx:yyy
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.Text(), nullable=False, server_default="enabled"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_menus_business", "menus", ["business_id"])

    if not _has(conn, "role_menus"):
        op.create_table(
            "role_menus",
            sa.Column("role", sa.Text(), primary_key=True),
            sa.Column("menu_id", sa.Text(), primary_key=True),
            sa.Column("business_id", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_role_menus_business", "role_menus", ["business_id"])

    if not _has(conn, "staff_members"):
        op.create_table(
            "staff_members",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("business_id", sa.Text(), nullable=False),
            sa.Column("email", sa.Text(), nullable=False),
            sa.Column("display_name", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=False, server_default="finance_owner"),
            sa.Column("status", sa.Text(), nullable=False, server_default="enabled"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_staff_business", "staff_members", ["business_id"])

    if not _has(conn, "analytics_reports"):
        op.create_table(
            "analytics_reports",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("business_id", sa.Text(), nullable=False),
            sa.Column("generated_by", sa.Text(), nullable=False),
            sa.Column("title", sa.Text(), nullable=False),
            sa.Column("time_window", sa.Text(), nullable=False),
            sa.Column("html", sa.Text(), nullable=False),
            sa.Column("rows_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_reports_business", "analytics_reports", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_business", table_name="analytics_reports")
    op.drop_table("analytics_reports")
    op.drop_index("ix_staff_business", table_name="staff_members")
    op.drop_table("staff_members")
    op.drop_index("ix_role_menus_business", table_name="role_menus")
    op.drop_table("role_menus")
    op.drop_index("ix_menus_business", table_name="menus")
    op.drop_table("menus")
