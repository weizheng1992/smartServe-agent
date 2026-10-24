"""0027 — 结构化画像槽位表 profile_slots(schema-guided profile)。

Revision ID: 0027_profile_slots
Revises: 0026_memory_fact_subject
Create Date: 2026-10-24

docs/memory-sota-upgrade.md P1#2:同 (user_id, subject, slot) 永远一行最新值
(UNIQUE + ON CONFLICT upsert)—— 尺码/荐品工具可消费的结构化档案,代买场景
(成员×槽位×值)的落点;写入方 long_memory._upsert_profile_slot(可变数字
维度与版型事实落库时同步 upsert)。自由文本 long_memory_facts 继续承载长尾。

- 幂等守卫:0001_baseline 以当前 models 动态 create_all,models.py 已含本表时
  全新库在 0001 即建好,本迁移直接执行必然 DuplicateTable —— 表存在即空转
  (同 0004/0025 守卫先例)。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0027_profile_slots"
down_revision = "0026_memory_fact_subject"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "profile_slots" in insp.get_table_names():
        return
    op.create_table(
        "profile_slots",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False, server_default=sa.text("'self'")),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0")),
        sa.Column("source", sa.Text(), server_default=sa.text("'agent_audit'")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "subject", "slot", name="uq_profile_slots_user_subject_slot"),
    )
    op.create_index("ix_profile_slots_user", "profile_slots", ["user_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "profile_slots" not in insp.get_table_names():
        return
    op.drop_index("ix_profile_slots_user", table_name="profile_slots")
    op.drop_table("profile_slots")
