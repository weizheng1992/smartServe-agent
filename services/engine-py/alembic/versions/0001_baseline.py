"""baseline — Alembic 从 Drizzle 手中接管 schema 所有权。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-02

以 SQLAlchemy models(单一事实源,35 张表)整体建库,等价于原 ``drizzle-kit push``
+ ``migrateColumns.ts`` 幂等 ALTER 的合并结果。

- 全新库:``alembic upgrade head`` 直接建全量。
- 存量库(Drizzle 已 push 过):先 ``alembic stamp head`` 登记版本,再走后续增量。
- 后续表结构变更:改 ``engine_py/db/models.py`` 后 ``alembic revision --autogenerate``。
"""

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from alembic import op
    from engine_py.db import Base

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from alembic import op
    from engine_py.db import Base

    Base.metadata.drop_all(bind=op.get_bind())
