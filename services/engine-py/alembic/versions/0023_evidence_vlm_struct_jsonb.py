"""0023 — after_sale_evidence.vlm_struct json → jsonb(0022 笔误对齐,2026-10-17)。

0022 把 vlm_struct 建成 sa.JSON()(PG 落 json),而 db/models.py 的
AfterSaleEvidence.vlm_struct 与 database-schema.md §1.1#11 均书 JSONB ——
迁移/模型/库三处漂,jsonb 算子与 autogenerate 从此失配。本迁移 ALTER 对齐;
jsonb::jsonb 重入无损、json::jsonb 有 USING 兜住,天然幂等。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0023_evidence_vlm_struct_jsonb"
down_revision = "0022_after_sale_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "after_sale_evidence"):
        conn.execute(
            sa.text(
                "ALTER TABLE after_sale_evidence ALTER COLUMN vlm_struct TYPE JSONB "
                "USING vlm_struct::jsonb"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "after_sale_evidence"):
        conn.execute(
            sa.text(
                "ALTER TABLE after_sale_evidence ALTER COLUMN vlm_struct TYPE JSON "
                "USING vlm_struct::json"
            )
        )
