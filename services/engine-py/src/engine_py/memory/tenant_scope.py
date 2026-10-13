"""记忆召回的租户作用域 SQL 条件(2026-09-21 拷问轮决议)。

文档(agent-engine.md §1.4)声称画像/情境召回在 SQL 层过滤租户,实现却只在
Python 侧后滤 —— 候选窗口(500/50)会被他租行挤占,高负载下本租记忆被顶掉。
本 helper 把过滤下沉 SQL,Python 侧 `_tenant_visible` 保留为防御纵深。

语义(与原 Python 过滤逐字对齐):
- scope 缺失或 global → 放行;
- scope=tenant 且当前租户有效(非空非 ecommerce)→ 仅 business_id 相等;
- scope=tenant 且当前无有效租户 → 仅 business_id 为空或 ecommerce。
"""

from __future__ import annotations

from sqlalchemy import and_, or_


def tenant_scope_condition(model, business_id: str | None):
    """model 需具 scope / business_id 两列;返回可并入 .where() 的 SQL 条件。"""
    bid = (business_id or "").strip()
    valid = bool(bid) and bid != "ecommerce"
    if valid:
        tenant_ok = model.business_id == bid
    else:
        # 空串与 NULL 同义(与旧 Python 过滤 `not row.business_id` 逐字对齐)
        tenant_ok = or_(
            model.business_id.is_(None), model.business_id == "", model.business_id == "ecommerce"
        )
    return or_(
        model.scope.is_(None),
        model.scope == "global",
        and_(model.scope == "tenant", tenant_ok),
    )
