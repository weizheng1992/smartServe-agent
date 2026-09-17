"""schema 卡片(08-D2:代码静态事实源,编译期生成,确定性进解析上下文)。

事实源 = gateway 侧 _MERCHANT_DDL(商户镜像库 7 表)的代码内声明;运行时
introspection 不进供给路径(漂移断言归 17 号票决议,独立模块)。
"""

from __future__ import annotations

from typing import Any

# 商户镜像库分析面(列裁剪:只暴露分析需要的列,token 成本 08-D2 实测 ≈1.5k)
_MERCHANT_TABLES: dict[str, dict[str, Any]] = {
    "merchant_spus": {
        "columns": {"id": "uuid 主键", "spu_code": "商品编码", "title": "商品标题", "category": "品类", "status": "ON_SALE/OFF_SALE"},
        "notes": "在售过滤 status='ON_SALE'",
    },
    "merchant_skus": {
        "columns": {"id": "uuid 主键", "spu_id": "→ merchant_spus.id", "price": "售价", "stock": "库存件数"},
        "notes": "展示价 = MIN(price);库存 = SUM(stock)",
    },
    "merchant_orders": {
        "columns": {"order_id": "订单号", "customer_id": "客户", "status": "PAID/SHIPPED/DELIVERED/REFUNDED/CANCELLED", "total_amount": "金额", "created_at": "下单时间"},
        "notes": "有效成交口径:status NOT IN (REFUNDED, CANCELLED)",
    },
    "merchant_order_items": {
        "columns": {"order_id": "→ merchant_orders.order_id", "spu_id": "商品编码(关联 spus.spu_code)", "quantity": "件数", "price": "成交价快照", "cost_at_purchase": "成交成本快照(NOT NULL)"},
        "notes": "销量 = SUM(quantity);GMV = SUM(quantity*price);成本求和不容 COALESCE",
    },
    "merchant_product_reviews": {
        "columns": {"id": "主键", "spu_id": "商品", "rating": "1-5 星", "sentiment": "情感", "content": "评语", "created_at": "时间"},
        "notes": "差评口径:rating <= 2",
    },
    "merchant_customers": {
        "columns": {"id": "主键", "email": "邮箱", "membership": "会员级"},
        "notes": "",
    },
    "merchant_audit_logs": {
        "columns": {"id": "主键", "actor": "操作者", "action": "动作", "created_at": "时间"},
        "notes": "审计面,分析只读可用",
    },
}


def merchant_schema_card() -> dict[str, Any]:
    """商户库 schema 卡片(全 7 表;冻结结构供 AST 校验与 L3 上下文)。"""
    return {"database": "agent_merchant", "tables": _MERCHANT_TABLES}


def schema_card_text() -> str:
    """紧凑文本形态(喂 L3 兜底层用;每表一行,列名拼接)。"""
    lines = []
    for table, spec in _MERCHANT_TABLES.items():
        cols = ", ".join(spec["columns"].keys())
        note = f" — {spec['notes']}" if spec["notes"] else ""
        lines.append(f"{table}({cols}){note}")
    return "\n".join(lines)
