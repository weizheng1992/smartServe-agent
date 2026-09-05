"""0003 — tenants 表增列 industry(所属行业)。

Revision ID: 0003_tenants_industry
Revises: 0002_badcase_candidates
Create Date: 2026-09-05

- 背景:admin 控制台租户编辑表单允许修改"所属行业",但该字段此前无处落盘
  (网关 tenant_list 硬编码 "综合零售"),编辑保存后被静默丢弃。
- 变更:``tenants`` 增列 ``industry TEXT NULL``;查询侧保留旧值回退("综合零售")。
- 幂等守卫(同 0002):0001_baseline 以当前 models 动态 create_all,models.py 已含
  本列时全新库在 0001 阶段即建好,0003 直接执行必然 DuplicateColumn;守卫后
  全新库空转,存量库正常补列。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_tenants_industry"
down_revision = "0002_badcase_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing_cols = {c["name"] for c in insp.get_columns("tenants")}
    if "industry" not in existing_cols:
        op.add_column("tenants", sa.Column("industry", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "industry")
