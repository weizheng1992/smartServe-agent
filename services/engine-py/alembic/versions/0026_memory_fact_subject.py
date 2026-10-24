"""0026 — 画像事实主体归属:long_memory_facts.subject。

Revision ID: 0026_memory_fact_subject
Revises: 0025_usage_turn_keys
Create Date: 2026-10-24

画像归属票(docs/ai-usage-panel 同日 grilling 延伸,实弹探针 2026-10-24):
「给妻子买衣服,她身高160」等代买场景此前把第三人身材记到 buyer 名下且与
本人事实混检索 —— 无主体维度,冲突防护全靠终稿 LLM 读自由文本。本迁移加
``subject`` 列('self'=本人,第三人存关系称谓),写侧同主体分组回声/覆盖,
读侧渲染主体前缀。

- 幂等守卫:0001_baseline 动态 create_all 已含本列时空转(同 0004 先例)。
- DEFAULT 'self' 回填存量行:PG 11+ 元数据级默认,重写无 IO。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0026_memory_fact_subject"
down_revision = "0025_usage_turn_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing_cols = {c["name"] for c in insp.get_columns("long_memory_facts")}
    if "subject" not in existing_cols:
        op.add_column(
            "long_memory_facts",
            sa.Column("subject", sa.Text(), nullable=False, server_default=sa.text("'self'")),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing_cols = {c["name"] for c in insp.get_columns("long_memory_facts")}
    if "subject" in existing_cols:
        op.drop_column("long_memory_facts", "subject")
