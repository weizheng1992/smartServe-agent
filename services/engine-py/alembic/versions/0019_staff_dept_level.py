"""0019 — staff_members 加 dept/level(「该找谁」责任人路由地基,2026-10-08)。

责任人 = 商户员工本体(staff_members 复用,不建第二套人名册):dept 部门
(销售/运营/售后/财务/仓储)、level 职级(店长/主管/专员)皆人事属性,
可空 = 未分配/未定级。展示与 owner 解析消费,不参与 RBAC 权限判定
(权限面仍由 role 三档闭集承载);升级路由(职级 fallback)留票不做。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0019_staff_dept_level"
down_revision = "0018_analytics_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("staff_members")}
    if "dept" not in cols:
        op.add_column("staff_members", sa.Column("dept", sa.Text(), nullable=True))
    if "level" not in cols:
        op.add_column("staff_members", sa.Column("level", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("staff_members", "level")
    op.drop_column("staff_members", "dept")
