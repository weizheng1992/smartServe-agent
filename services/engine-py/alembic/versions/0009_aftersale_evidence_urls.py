"""0009 — after_sale_tickets 增列 evidence_urls(售后凭证落票,ADR-0002)。

Revision ID: 0009_aftersale_evidence
Revises: 0008_onboarding
Create Date: 2026-09-12

- ``after_sale_tickets`` 增列 ``evidence_urls``(JSONB 数组,默认 '[]'):用户
  申报售后时本轮上传的瑕疵凭证(``/api/uploads/...`` 相对 URL,≤3 张与引擎
  视觉上限一致);人工审批员处理工单时看单即看图,售后闭环补上最后一环。
- 幂等守卫:0001_baseline 以当前 models 动态 create_all,models.py 已含本列时
  全新库在 0001 即建好,0009 直接执行必然 DuplicateColumn,守卫后空转
  (沿 0006_messages_image_urls 先例)。
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_aftersale_evidence"
down_revision = "0008_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {c["name"] for c in inspector.get_columns("after_sale_tickets")}
    if "evidence_urls" in columns:
        return
    op.add_column(
        "after_sale_tickets",
        sa.Column("evidence_urls", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=True),
    )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {c["name"] for c in inspector.get_columns("after_sale_tickets")}
    if "evidence_urls" not in columns:
        return
    op.drop_column("after_sale_tickets", "evidence_urls")
