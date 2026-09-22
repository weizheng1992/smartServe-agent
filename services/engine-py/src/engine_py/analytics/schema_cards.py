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


# 阶段③ special-family 闭集模板专用的额外表(活动核销 2 表在商户镜像库,
# 会话/售后 2 表在 engine 本地库)。不进 schema_card_text()(L3 上下文只喂
# 商户 7 表,token 成本 08-D2 冻结);仅参与编译期 AST 表白名单。
_SPECIAL_FAMILY_TABLES: dict[str, dict[str, Any]] = {
    "promotions": {
        "columns": {"id": "主键", "name": "活动名"},
        "notes": "",
    },
    "promotion_redemptions": {
        "columns": {"promotion_id": "→ promotions.id", "order_id": "→ merchant_orders.order_id", "discount_amount": "优惠金额", "created_at": "核销时间"},
        "notes": "核销关联口径:真实归因,自然流量不计入",
    },
    "session_metrics": {
        "columns": {"business_id": "租户", "resolution_status": "resolved_auto/未解决", "created_at": "时间"},
        "notes": "engine 本地库;查询必带 business_id 谓词",
    },
    "after_sale_tickets": {
        "columns": {"business_id": "租户", "status": "工单状态", "created_at": "时间"},
        "notes": "engine 本地库;查询必带 business_id 谓词",
    },
    "user_coupons": {
        "columns": {"user_id": "客户ID(= merchant_customers.customer_id)", "promotion_id": "→ promotions.id", "status": "claimed/used", "claimed_at": "领取时间", "used_at": "核销时间"},
        "notes": "商城券包;客户实体过滤",
    },
}


def compile_safe_schema_card() -> dict[str, Any]:
    """编译期安全闸联合卡(商户 7 表 + special-family 4 表)。

    两条编译路径(销售族/特殊族)统一喂这一张表,保证模板新增表必须先在
    事实源登记,否则安全闸响亮拒绝 —— 表白名单单点收口。
    """
    return {"database": "agent_merchant", "tables": {**_MERCHANT_TABLES, **_SPECIAL_FAMILY_TABLES}}


def schema_card_text() -> str:
    """紧凑文本形态(喂 L3 兜底层用;每表一行,列名拼接)。"""
    lines = []
    for table, spec in _MERCHANT_TABLES.items():
        cols = ", ".join(spec["columns"].keys())
        note = f" — {spec['notes']}" if spec["notes"] else ""
        lines.append(f"{table}({cols}){note}")
    return "\n".join(lines)
