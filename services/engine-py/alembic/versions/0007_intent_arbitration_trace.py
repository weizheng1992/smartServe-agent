"""0007 — intent_logs 仲裁留痕三列(intent-arbitration 01)。

Revision ID: 0007_intent_arbit
Revises: 0006_messages_images
Create Date: 2026-09-10

- ``intent_logs`` 增列 ``candidates``(JSONB,各判定层提议快照,形如
  ``[{"layer": "slot_extractor", "intent": "order_return", "confidence": 0.95}]``)、
  ``winner``(Text,终局胜者意图)、``arbitration_reason``(Text,裁决理由,
  旁路路径默认取 route_key)。
- 背景:槽位层与 skill_fast_track 曾对同一输入双写两行且无仲裁记录,
  「分类器宣称 vs 落库胜者」的挖掘口径无处可查;终局决策收口单点落库后,
  本三列承载完整仲裁链(坏例池冲突信号源与冲突触发仲裁共同消费)。
- 幂等守卫:0001_baseline 以当前 models 动态 create_all,models.py 已含
  本列时全新库在 0001 即建好,本迁移空转。
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_intent_arbit"
down_revision = "0006_messages_images"
branch_labels = None
depends_on = None

_NEW_COLUMNS = ("candidates", "winner", "arbitration_reason")


def _existing_cols() -> set[str]:
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns("intent_logs")}


def upgrade() -> None:
    existing = _existing_cols()
    if "candidates" not in existing:
        op.add_column("intent_logs", sa.Column("candidates", postgresql.JSONB(), nullable=True))
    if "winner" not in existing:
        op.add_column("intent_logs", sa.Column("winner", sa.Text(), nullable=True))
    if "arbitration_reason" not in existing:
        op.add_column("intent_logs", sa.Column("arbitration_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    existing = _existing_cols()
    for col in _NEW_COLUMNS:
        if col in existing:
            op.drop_column("intent_logs", col)
