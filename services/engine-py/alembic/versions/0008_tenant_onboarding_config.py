"""0008 — tenant_configs 增列 onboarding_config(JSONB,new-user-onboarding A)。

Revision ID: 0008_onboarding
Revises: 0007_intent_arbit
Create Date: 2026-09-10

- 新用户引导话术结构化配置:欢迎文案(welcomeText)、回访轻问候
  (returningGreeting)、能力入口快捷按钮(quickReplies)三段由租户级
  JSONB 承载,缺省/部分缺失按字段回落平台默认(解析见 engine_py/onboarding.py)。
- 既有 ``welcome_message``(Text,只写不读)就此获得消费方:作为
  welcomeText 的第二优先级回退源,平滑存量租户。
- 幂等守卫:0001_baseline 以当前 models 动态 create_all,models.py 已含
  本列时全新库在 0001 即建好,本迁移空转。
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0008_onboarding"
down_revision = "0007_intent_arbit"
branch_labels = None
depends_on = None


def _existing_cols() -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns("tenant_configs")}


def upgrade() -> None:
    if "onboarding_config" not in _existing_cols():
        op.add_column("tenant_configs", sa.Column("onboarding_config", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    if "onboarding_config" in _existing_cols():
        op.drop_column("tenant_configs", "onboarding_config")
