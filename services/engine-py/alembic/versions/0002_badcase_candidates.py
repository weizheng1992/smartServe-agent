"""0002 — badcase_candidates 候选池表 + session_metrics 熔断计数列(第五阶段 v1)。

Revision ID: 0002_badcase_candidates
Revises: 0001_baseline
Create Date: 2026-09-03

- 新增 ``badcase_candidates``:Bad-Case 半自动闭环的信号候选池(只存引用不存原文)。
- ``session_metrics`` 增列 ``global_transitions_count`` / ``tool_errors_count``:
  图级熔断(10 步/3 错)计数落盘,配套 ``resolution_status = 'circuit_breaker'``。
- 注意:autogenerate 会误判 third_party_* 五张表为"待删除"(它们归 gateway-py
  商户域所有,有意不在 engine-py 模型内),本迁移已手工剔除该差异。
- 幂等守卫(必须):``0001_baseline`` 以当前 models 动态 ``create_all`` 建全量表,
  models.py 已含本迁移的表/列时,全新库在 0001 阶段即建好,0002 直接执行必然
  DuplicateTable/DuplicateColumn。守卫后:全新库 0002 空转,存量库(0001 先于
  本变更执行)正常补建。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_badcase_candidates"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if not insp.has_table("badcase_candidates"):
        op.create_table(
            "badcase_candidates",
            sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("signal_source", sa.Text(), nullable=False),
            sa.Column("conversation_ref", sa.Text(), nullable=False),
            sa.Column("business_id", sa.Text(), nullable=False),
            sa.Column("suggested_class", sa.Text(), server_default=sa.text("'neutral'"), nullable=True),
            sa.Column("status", sa.Text(), server_default=sa.text("'candidate'"), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_badcase_candidates_status_created", "badcase_candidates", ["status", "created_at"])

    existing_metric_cols = {c["name"] for c in insp.get_columns("session_metrics")}
    if "global_transitions_count" not in existing_metric_cols:
        op.add_column(
            "session_metrics",
            sa.Column("global_transitions_count", sa.Integer(), server_default=sa.text("0"), nullable=True),
        )
    if "tool_errors_count" not in existing_metric_cols:
        op.add_column(
            "session_metrics",
            sa.Column("tool_errors_count", sa.Integer(), server_default=sa.text("0"), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("session_metrics", "tool_errors_count")
    op.drop_column("session_metrics", "global_transitions_count")
    op.drop_index("ix_badcase_candidates_status_created", table_name="badcase_candidates")
    op.drop_table("badcase_candidates")
