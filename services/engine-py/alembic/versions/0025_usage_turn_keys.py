"""0025 — 用量面板轮关联键:llm_call_logs.job_id + session_metrics.job_id/turn_path。

Revision ID: 0025_usage_turn_keys
Revises: 0024_merchant_credits
Create Date: 2026-10-24

docs/ai-usage-panel.md P0-1(2026-10-24 grilling 共识):轮↔调用精确关联是
用量页「面=轮、下钻=调用」的地基 —— 此前 llm_call_logs 无任何轮标识
(CallContext.job_id 现成但未入行),轮边界只能靠 thread_id+时间近似切;
session_metrics 本就每轮一行,补 job_id/turn_path 后轮路径成为一等公民
(零 LLM 命中率/快轨占比的聚合源),进图前问候旁路自此补写零 token 行。

- 幂等守卫:0001_baseline 以当前 models 动态 create_all,models.py 已含
  本列时全新库在 0001 即建好,本迁移按列名守卫后空转(同 0004 先例)。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0025_usage_turn_keys"
down_revision = "0024_merchant_credits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    llm_cols = {c["name"] for c in insp.get_columns("llm_call_logs")}
    if "job_id" not in llm_cols:
        op.add_column("llm_call_logs", sa.Column("job_id", sa.Text(), nullable=True))

    session_cols = {c["name"] for c in insp.get_columns("session_metrics")}
    if "job_id" not in session_cols:
        op.add_column("session_metrics", sa.Column("job_id", sa.Text(), nullable=True))
    if "turn_path" not in session_cols:
        op.add_column("session_metrics", sa.Column("turn_path", sa.Text(), nullable=True))

    llm_idx = {i["name"] for i in insp.get_indexes("llm_call_logs")}
    if "llm_log_job_idx" not in llm_idx:
        op.create_index("llm_log_job_idx", "llm_call_logs", ["job_id"])
    session_idx = {i["name"] for i in insp.get_indexes("session_metrics")}
    if "session_metrics_job_idx" not in session_idx:
        op.create_index("session_metrics_job_idx", "session_metrics", ["job_id"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())

    session_idx = {i["name"] for i in insp.get_indexes("session_metrics")}
    if "session_metrics_job_idx" in session_idx:
        op.drop_index("session_metrics_job_idx", table_name="session_metrics")
    llm_idx = {i["name"] for i in insp.get_indexes("llm_call_logs")}
    if "llm_log_job_idx" in llm_idx:
        op.drop_index("llm_log_job_idx", table_name="llm_call_logs")

    session_cols = {c["name"] for c in insp.get_columns("session_metrics")}
    if "turn_path" in session_cols:
        op.drop_column("session_metrics", "turn_path")
    if "job_id" in session_cols:
        op.drop_column("session_metrics", "job_id")
    llm_cols = {c["name"] for c in insp.get_columns("llm_call_logs")}
    if "job_id" in llm_cols:
        op.drop_column("llm_call_logs", "job_id")
