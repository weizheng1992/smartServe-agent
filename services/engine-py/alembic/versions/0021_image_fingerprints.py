"""0021 — image_fingerprints 图证内容指纹账本(视觉加固 ②①期,2026-10-17)。

「这张图是否已被别的人拿来索赔过」的事实源:引擎侧 vision 评级时读本地图算
SHA-256,先查后记;同 (business_id, sha256) 已有不同 user 的先前记录即跨用户
复用命中,命中只降级(suggestedAction→human_review + fraudFlag)绝不拒赔。
同 URL 幂等(UNIQUE,多轮重分析不重复记账);只存哈希不存图内容。
消费方:engine_py/vision/fingerprints.py(triage Step 0.5 后反查)。
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "0021_image_fingerprints"
down_revision = "0020_wh_strip_system_menus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "image_fingerprints"):
        return
    op.create_table(
        "image_fingerprints",
        sa.Column("id", sa.Text(), primary_key=True),  # fp_<hex12>
        sa.Column("business_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),  # /api/uploads/<uuid> 全局唯一
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),  # 匿名上传留空,不参与跨用户判定
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_image_fingerprints_url", "image_fingerprints", ["url"], unique=True)
    op.create_index("image_fingerprints_biz_sha_idx", "image_fingerprints", ["business_id", "sha256"])


def downgrade() -> None:
    op.drop_index("image_fingerprints_biz_sha_idx", table_name="image_fingerprints")
    op.drop_index("uq_image_fingerprints_url", table_name="image_fingerprints")
    op.drop_table("image_fingerprints")
