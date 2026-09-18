"""0011 — query_exemplars 查询示例库(wayfinder 08-D3 L2 层;阶段③)。

data agent 的 few-shot 示例双池之一(全局共享池:business_id='__global__';
租户池按 business_id 隔离)。与 intent_exemplars 分表 —— 标注结构不同
(此处 intent_json 存结构化查询意图 {metric,direction,...},非意图名),
严禁扩 intent_exemplars 列污染意图分类语义(08-D3 决议)。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0011_query_exemplars"
down_revision = "0010_aftersale_no_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "query_exemplars"):
        return
    op.create_table(
        "query_exemplars",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("intent_json", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_query_exemplars_business", "query_exemplars", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_query_exemplars_business", table_name="query_exemplars")
    op.drop_table("query_exemplars")
