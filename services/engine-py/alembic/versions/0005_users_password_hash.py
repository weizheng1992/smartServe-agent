"""0005 — users 增列 password_hash(auth/login 真实化)。

Revision ID: 0005_users_password
Revises: 0004_llm_call_logs_biz
Create Date: 2026-09-06

- ``users`` 增列 ``password_hash``(可空):gateway ``/api/auth/login`` 以 bcrypt
  校验登录凭证;NULL 表示未设密码账号(不可密码登录),存量行保持 NULL。
- 幂等守卫:0001_baseline 以当前 models 动态 create_all,models.py 已含本列时
  全新库在 0001 即建好,0005 直接执行必然 DuplicateColumn,守卫后空转。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_users_password"
down_revision = "0004_llm_call_logs_biz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    existing_cols = {c["name"] for c in insp.get_columns("users")}
    if "password_hash" not in existing_cols:
        op.add_column("users", sa.Column("password_hash", sa.Text(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())

    existing_cols = {c["name"] for c in insp.get_columns("users")}
    if "password_hash" in existing_cols:
        op.drop_column("users", "password_hash")
