"""0015 — data agent 未命中问句沉淀表(ADR-0005 增长飞轮输入口)。

unsupported 的问题一问一行(business_id/role/question);定期聚类高频问句
→ 决定语义层下一步登记哪些维度/指标。幂等:表已存在时跳过。
"""

import sqlalchemy as sa

from alembic import op

revision = "0015_agent_unanswered"
down_revision = "0014_drop_approvals_menu"
branch_labels = None
depends_on = None


def _has(conn, table: str) -> bool:
    return conn.dialect.has_table(conn, table)


def upgrade() -> None:
    conn = op.get_bind()
    if _has(conn, "agent_unanswered"):
        return
    op.create_table(
        "agent_unanswered",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="finance_owner"),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_unanswered_business", "agent_unanswered", ["business_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if _has(conn, "agent_unanswered"):
        op.drop_table("agent_unanswered")
