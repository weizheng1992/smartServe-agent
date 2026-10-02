"""0017 — intent_logs 会话维度索引(2026-10-02 夜审修复C)。

intent_logs.thread_id 是仲裁留痕按会话回查的唯一入口(triage/labeling.py
标注水龙头逐 thread 点查;0016 只补了 created_at 审计翻页),单 FK 无索引
即逐条全表扫。按 0016 的 pending_approvals_thread_created_idx 同款形状立
(thread_id, created_at) 复合 —— 等值 thread 在前,时间序随后,一并覆盖
会话内留痕的时间扫描。幂等:CREATE INDEX IF NOT EXISTS。
"""

import sqlalchemy as sa

from alembic import op

revision = "0017_intent_logs_thread_index"
down_revision = "0016_hot_path_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            'CREATE INDEX IF NOT EXISTS "intent_logs_thread_created_idx" '
            'ON "intent_logs" ("thread_id", "created_at")'
        )
    )


def downgrade() -> None:
    op.drop_index("intent_logs_thread_created_idx")
