"""0006 — messages 增列 image_urls(多模态图片持久化)。

Revision ID: 0006_messages_images
Revises: 0005_users_password
Create Date: 2026-09-08

- ``messages`` 增列 ``image_urls``(JSONB 数组,可空):用户消息携带的图片引用
  (``/api/uploads/...`` 相对 URL),只存引用不存 blob;历史读取原样带回,
  web 刷新还原缩略图(wayfinder multimodal 004)。
- 幂等守卫:0001_baseline 以当前 models 动态 create_all,models.py 已含本列时
  全新库在 0001 即建好,0006 直接执行必然 DuplicateColumn,守卫后空转。
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_messages_images"
down_revision = "0005_users_password"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    existing_cols = {c["name"] for c in insp.get_columns("messages")}
    if "image_urls" not in existing_cols:
        op.add_column("messages", sa.Column("image_urls", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())

    existing_cols = {c["name"] for c in insp.get_columns("messages")}
    if "image_urls" in existing_cols:
        op.drop_column("messages", "image_urls")
