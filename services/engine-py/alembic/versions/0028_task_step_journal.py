"""0028 — 步级执行日志表 task_step_journal(崩溃恢复真值源)。

Revision ID: 0028_task_step_journal
Revises: 0027_profile_slots
Create Date: 2026-10-24

docs/multi-turn-task-state.md P2-1/D5:append-only 步级日志(每子任务状态
变化一行 ok/failed),修复「执行中崩溃 → 降级臂用空桩覆写在途计划 → 恢复面
无从谈起」。写入方 graph/nodes/executor.py 的进出 plan diff;消费方
memory/step_journal.py 的 detect_crash_tail(轮入口恢复载回)。

- 幂等守卫:0001_baseline 以当前 models 动态 create_all,models.py 已含本表时
  全新库在 0001 即建好,本迁移直接执行必然 DuplicateTable —— 表存在即空转
  (同 0004/0025/0027 守卫先例)。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0028_task_step_journal"
down_revision = "0027_profile_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "task_step_journal" in insp.get_table_names():
        return
    op.create_table(
        "task_step_journal",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("result_digest", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_index("ix_task_step_journal_thread_created", "task_step_journal", ["thread_id", "created_at"])
    op.create_index("ix_task_step_journal_job", "task_step_journal", ["job_id"])


def downgrade() -> None:
    op.drop_table("task_step_journal")
