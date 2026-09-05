"""0004 — llm_call_logs 租户归因列 + 查询索引(LLM 调用日志接线)。

Revision ID: 0004_llm_call_logs_biz
Revises: 0003_tenants_industry
Create Date: 2026-09-05

- ``llm_call_logs`` 增列 ``business_id``(可空):写入方为 engine_py/llm/telemetry.py
  的统一捕获 handler(每次 LLM 调用真实 usage/延迟落盘),admin /api/logs 按租户
  过滤依赖该列(架构不变量 #1:业务表必须携带租户边界)。
- 历史行(接线前)与图外调用(无租户上下文)保持 NULL,由查询侧 outerjoin
  threads 兜底归因,不回填假值。
- 幂等守卫:0001_baseline 以当前 models 动态 create_all,models.py 已含本列时
  全新库在 0001 即建好,0004 直接执行必然 DuplicateColumn,守卫后空转。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_llm_call_logs_biz"
down_revision = "0003_tenants_industry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())

    existing_cols = {c["name"] for c in insp.get_columns("llm_call_logs")}
    if "business_id" not in existing_cols:
        op.add_column("llm_call_logs", sa.Column("business_id", sa.Text(), nullable=True))

    existing_idx = {i["name"] for i in insp.get_indexes("llm_call_logs")}
    if "llm_log_biz_created_idx" not in existing_idx:
        op.create_index("llm_log_biz_created_idx", "llm_call_logs", ["business_id", "created_at"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    existing_idx = {i["name"] for i in insp.get_indexes("llm_call_logs")}
    if "llm_log_biz_created_idx" in existing_idx:
        op.drop_index("llm_log_biz_created_idx", table_name="llm_call_logs")
    existing_cols = {c["name"] for c in insp.get_columns("llm_call_logs")}
    if "business_id" in existing_cols:
        op.drop_column("llm_call_logs", "business_id")
