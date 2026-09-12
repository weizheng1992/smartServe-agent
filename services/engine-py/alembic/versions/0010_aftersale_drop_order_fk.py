"""0010 — after_sale_tickets 去除 order_id 外键(订单双源现实,ADR-0002)。

Revision ID: 0010_aftersale_no_fk
Revises: 0009_aftersale_evidence
Create Date: 2026-09-12

- 售后工单的 order_id 此前 FK 指向 engine 本地 ``orders`` 表,而商户真单存于
  agent_merchant.merchant_orders —— 商户单的售后工单**永远**违反外键插不进去,
  且异常被吞后返回假 ``success: True``(2026-09-12 实弹抓出)。去 FK 后
  order_id 仅作双源引用。
- 幂等:constraint 不存在时空转。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010_aftersale_no_fk"
down_revision = "0009_aftersale_evidence"
branch_labels = None
depends_on = None

_FK_NAME = "after_sale_tickets_order_id_fkey"


def upgrade() -> None:
    conn = op.get_bind()
    fks = {fk["name"] for fk in conn.dialect.get_foreign_keys(conn, "after_sale_tickets")}
    if _FK_NAME in fks:
        op.drop_constraint(_FK_NAME, "after_sale_tickets", type_="foreignkey")


def downgrade() -> None:
    conn = op.get_bind()
    fks = {fk["name"] for fk in conn.dialect.get_foreign_keys(conn, "after_sale_tickets")}
    if _FK_NAME not in fks:
        op.create_foreign_key(_FK_NAME, "after_sale_tickets", "orders", ["order_id"], ["order_id"])
