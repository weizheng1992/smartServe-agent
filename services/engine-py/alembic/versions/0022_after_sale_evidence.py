"""0022 — after_sale_evidence 证据表 + after_sale_tickets.fast_lane_denied(A2,2026-10-17)。

视觉加固 issues/05:apply_after_sale 落票时把当轮 vision_analysis 快照进证据表
(stage='apply',receive 阶段为 B 节点收货质检预留),叠加纯规则闸——图证单号与
所退订单不符 / 带图轮零凭证 → fast_lane_denied=true,processRefund 免签通道对
该单关闭(走既有 HITL),只收紧不放宽、绝不拒赔。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0022_after_sale_evidence"
down_revision = "0021_image_fingerprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if not conn.dialect.has_table(conn, "after_sale_evidence"):
        op.create_table(
            "after_sale_evidence",
            sa.Column("id", sa.Text(), primary_key=True),  # ase_<hex12>
            sa.Column("business_id", sa.Text(), nullable=False),
            sa.Column("ticket_id", sa.Text(), nullable=False),
            sa.Column("stage", sa.Text(), nullable=False),  # 'apply' | 'receive'(B 节点预留)
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("vlm_struct", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index(
            "uq_after_sale_evidence_ticket_stage_url",
            "after_sale_evidence",
            ["ticket_id", "stage", "url"],
            unique=True,
        )
        op.create_index("after_sale_evidence_biz_idx", "after_sale_evidence", ["business_id"])
    conn.execute(
        sa.text(
            "ALTER TABLE after_sale_tickets ADD COLUMN IF NOT EXISTS fast_lane_denied "
            "BOOLEAN NOT NULL DEFAULT false"
        )
    )


def downgrade() -> None:
    op.drop_index("after_sale_evidence_biz_idx", table_name="after_sale_evidence")
    op.drop_index("uq_after_sale_evidence_ticket_stage_url", table_name="after_sale_evidence")
    op.drop_table("after_sale_evidence")
    op.execute("ALTER TABLE after_sale_tickets DROP COLUMN IF EXISTS fast_lane_denied")
