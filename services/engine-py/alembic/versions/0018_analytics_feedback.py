"""0018 — analytics_feedback 答案反馈台账(反馈闭环 v3.1,2026-10-06)。

员工对 data agent 答案 👍/👎 的事实总账:一次 trace × 一位员工一行
(UNIQUE business_id+trace_id+staff,改判即 upsert,last verdict wins)。
badcase_id/exemplar_id 记本路径扇出产物 id,供改判补偿(撤 user 范例/
dismiss 坏例信号)凭据回查;question/metric/layers_json 为反馈时点快照,
采纳率统计不依赖 analytics_trace 的未来清理策略。行动结果在两池
(badcase_candidates / query_exemplars),本表只做事实源 —— 两者严禁混算。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0018_analytics_feedback"
down_revision = "0017_intent_logs_thread_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "analytics_feedback"):
        return
    op.create_table(
        "analytics_feedback",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("staff", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=True),
        sa.Column("layers_json", sa.JSON(), nullable=True),
        sa.Column("badcase_id", sa.Text(), nullable=True),
        sa.Column("exemplar_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("business_id", "trace_id", "staff", name="uq_analytics_feedback_staff_trace"),
    )
    op.create_index("ix_analytics_feedback_business", "analytics_feedback", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_analytics_feedback_business", table_name="analytics_feedback")
    op.drop_table("analytics_feedback")
