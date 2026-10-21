"""0024 — merchant_credit_accounts + credit_transactions(用量配额闸,2026-10-21)。

游客 10 次免费 + 商户积分池(.scratch/agent-usage-quota/spec.md):余额唯一
真相在 merchant_credit_accounts(网关闸单语句原子扣减);credit_transactions
只追加台账,refund 部分唯一索引以 ref_job_id 挡双退。既有 token 观测面
tenant_billing_quotas 不动(两套计价互不干涉)。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0024_merchant_credits"
down_revision = "0023_evidence_vlm_struct_jsonb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if not conn.dialect.has_table(conn, "merchant_credit_accounts"):
        op.create_table(
            "merchant_credit_accounts",
            sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("business_id", sa.Text(), nullable=False),
            sa.Column("balance", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("uq_merchant_credit_accounts_business", "merchant_credit_accounts", ["business_id"], unique=True)
    if not conn.dialect.has_table(conn, "credit_transactions"):
        op.create_table(
            "credit_transactions",
            sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("business_id", sa.Text(), nullable=False),
            sa.Column("delta", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),  # initial_grant|consume|refund|admin_adjust
            sa.Column("ref_job_id", sa.Text(), nullable=True),
            sa.Column("operator", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("credit_transactions_biz_idx", "credit_transactions", ["business_id"])
        op.create_index(
            "uq_credit_transactions_refund_job",
            "credit_transactions",
            ["business_id", "ref_job_id"],
            unique=True,
            postgresql_where=sa.text("reason = 'refund'"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "credit_transactions"):
        op.drop_index("uq_credit_transactions_refund_job", table_name="credit_transactions")
        op.drop_index("credit_transactions_biz_idx", table_name="credit_transactions")
        op.drop_table("credit_transactions")
    if conn.dialect.has_table(conn, "merchant_credit_accounts"):
        op.drop_index("uq_merchant_credit_accounts_business", table_name="merchant_credit_accounts")
        op.drop_table("merchant_credit_accounts")
