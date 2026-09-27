"""0016 — 热路径索引补齐(2026-09-27 夜审 F1)。

四处高频查询此前全表扫:threads 侧栏列表(user_id + updated_at 倒序)、
session_metrics 管理大盘聚合(business_id + created_at)、intent_logs 审计
翻页(created_at)、pending_approvals HITL 轮询(status + created_at;
web 2s / admin 5s 各自全表扫)与会话历史回查(thread_id + created_at)。
幂等:索引已存在时跳过(PG CREATE INDEX IF NOT EXISTS)。
"""

import sqlalchemy as sa

from alembic import op

revision = "0016_hot_path_indexes"
down_revision = "0015_agent_unanswered"
branch_labels = None
depends_on = None

_TARGETS = [
    ("threads_user_updated_idx", "threads", ["user_id", "updated_at"]),
    ("session_metrics_biz_created_idx", "session_metrics", ["business_id", "created_at"]),
    ("intent_logs_created_at_idx", "intent_logs", ["created_at"]),
    ("pending_approvals_status_created_idx", "pending_approvals", ["status", "created_at"]),
    ("pending_approvals_thread_created_idx", "pending_approvals", ["thread_id", "created_at"]),
]


def upgrade() -> None:
    conn = op.get_bind()
    for name, table, cols in _TARGETS:
        conn.execute(
            sa.text(
                f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ('
                + ", ".join(f'"{c}"' for c in cols)
                + ")"
            )
        )


def downgrade() -> None:
    for name, _table, _cols in _TARGETS:
        op.drop_index(name)
