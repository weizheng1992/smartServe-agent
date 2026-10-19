"""本体知识层编译产物 —— GENERATED,手改无效(漂移门 test_codegen_sync 钉死)。

源头:ontology/{core,domain,application}/*.yaml,经 ontology/registry.py 编译;
再生成:仓库根执行 `services/.venv/bin/python ontology/registry.py --write`。
消费方(ADR-0015 批一):engine approvals/gatekeeper(受理集+早退 400+阈值缺省)、
graph/nodes/step_execution_engine(免签限额)、gateway approval_actions(四词表派生再出口)。
"""

from __future__ import annotations

from typing import Final

# --- 动作面(application/actions.yaml)--------------------------------------
APPROVAL_ACTIONS: Final[dict[str, dict[str, object]]] = {
    "approve": {
        'label': "审批通过",
        'faces': ('customer', 'staff_review', 'spi'),
        'permission': 'live_desk:approve',
        'roles': ('platform_admin', 'merchant_operator', 'system', 'customer'),
        'requires_approval_id': True,
        'notes': "human_escalation 工单 → resolved_by_human;其余 → approved",
    },
    "reject": {
        'label': "审批驳回",
        'faces': ('customer', 'staff_review', 'spi'),
        'permission': 'live_desk:approve',
        'roles': ('platform_admin', 'merchant_operator', 'system', 'customer'),
        'requires_approval_id': True,
        'notes': "2026-10-19 前无显式分支、靠 next_status 初值兜底——未知动作静默驳回与之 同路(gatekeeper else 兜底);现显式分支 + 引擎早退 400 双闸收口(ADR-0015 批一)",
    },
    "cancel": {
        'label': "取消工单",
        'faces': ('customer', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator', 'system', 'customer'),
        'requires_approval_id': True,
        'notes': "→ cancelled",
    },
    "start_human_takeover": {
        'label': "呼叫人工接管",
        'faces': ('customer', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator', 'system', 'customer'),
        'requires_approval_id': False,
        'notes': "无 operator 即呼叫排队形态;带 operator 即认领(P1 坐席身份)",
    },
    "human_message": {
        'label': "坐席发言(不结束)",
        'faces': ('operator', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator'),
        'requires_approval_id': True,
        'notes': "带 operator 落 role=operator 列;无身份旧通道前缀写(P5 退役)",
    },
    "human_finish": {
        'label': "坐席结案",
        'faces': ('operator', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator'),
        'requires_approval_id': True,
        'notes': "→ resolved_by_human + 释放接管(幂等)",
    },
    "release_takeover": {
        'label': "释放人工接管",
        'faces': ('operator', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator'),
        'requires_approval_id': False,
        'notes': "线程级动作(P1),条件 UPDATE 幂等;网关按线程归属校验租户",
    },
    "human_reply": {
        'label': "人工回复(SPI 旧通道)",
        'faces': ('spi',),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator'),
        'requires_approval_id': True,
        'notes': "SPI 面仍合法(P4 只收管理台面);引擎分支保留至 P5",
    },
}

CUSTOMER_ACTIONS: Final[frozenset[str]] = frozenset(['approve', 'cancel', 'reject', 'start_human_takeover'])
OPERATOR_ACTIONS: Final[frozenset[str]] = frozenset(['human_finish', 'human_message', 'release_takeover'])
STAFF_REVIEW_ACTIONS: Final[frozenset[str]] = frozenset(['approve', 'reject'])
SPI_ACTIONS: Final[frozenset[str]] = frozenset(['approve', 'cancel', 'human_finish', 'human_message', 'human_reply', 'reject', 'release_takeover', 'start_human_takeover'])
ENGINE_HANDLED_ACTIONS: Final[frozenset[str]] = frozenset(APPROVAL_ACTIONS)
TS_GHOST_ACTIONS: Final[frozenset[str]] = frozenset(['reply'])

# --- 实体与 schema 卡(domain 投影;批二 schema_cards/manifest 派生源)-------
ONTOLOGY_ENTITIES: Final[dict[str, dict[str, object]]] = {
    "merchant_customers": {
        'domain': "crm",
        'table': "merchant_customers",
        'database': "merchant_db",
        'alias': "c",
        'label': "客户",
        'columns': {
            "id": "主键",
            "customer_id": "客户编号",
            "name": "姓名",
            "phone": "手机号",
            "member_level": "会员级",
            "created_at": "注册时间",
        },
        'notes': "",
    },
    "promotions": {
        'domain': "marketing",
        'table': "promotions",
        'database': "merchant_db",
        'alias': "p",
        'label': "优惠活动",
        'columns': {
            "id": "主键",
            "name": "活动名",
        },
        'notes': "",
    },
    "promotion_redemptions": {
        'domain': "marketing",
        'table': "promotion_redemptions",
        'database': "merchant_db",
        'alias': "rd",
        'label': "活动核销",
        'columns': {
            "promotion_id": "→ promotions.id",
            "order_id": "→ merchant_orders.order_id",
            "discount_amount": "优惠金额",
            "created_at": "核销时间",
        },
        'notes': "核销关联口径:真实归因,自然流量不计入",
    },
    "user_coupons": {
        'domain': "marketing",
        'table': "user_coupons",
        'database': "merchant_db",
        'alias': "uc",
        'label': "用户券包",
        'columns': {
            "user_id": "客户ID(= merchant_customers.customer_id)",
            "promotion_id": "→ promotions.id",
            "status": "claimed/used",
            "claimed_at": "领取时间",
            "used_at": "核销时间",
        },
        'notes': "客户实体过滤",
    },
    "merchant_spus": {
        'domain': "product",
        'table': "merchant_spus",
        'database': "merchant_db",
        'alias': "s",
        'label': "商品 SPU",
        'columns': {
            "id": "uuid 主键",
            "spu_code": "商品编码(明细表关联键)",
            "title": "商品标题",
            "category": "品类",
            "brand": "品牌",
            "status": "ON_SALE/OFF_SALE",
        },
        'notes': "在售过滤 status='ON_SALE'",
    },
    "merchant_skus": {
        'domain': "product",
        'table': "merchant_skus",
        'database': "merchant_db",
        'alias': "k",
        'label': "商品 SKU",
        'columns': {
            "id": "uuid 主键",
            "spu_id": "→ merchant_spus.id",
            "price": "售价",
            "stock": "库存件数",
        },
        'notes': "展示价 = MIN(price);库存 = SUM(stock)",
    },
    "merchant_product_reviews": {
        'domain': "product",
        'table': "merchant_product_reviews",
        'database': "merchant_db",
        'alias': "r",
        'label': "商品评价",
        'columns': {
            "id": "主键",
            "spu_id": "商品",
            "rating": "1-5 星",
            "content": "评语",
            "created_at": "时间",
        },
        'notes': "差评口径:rating <= 2",
    },
    "merchant_audit_logs": {
        'domain': "shared",
        'table': "merchant_audit_logs",
        'database': "merchant_db",
        'alias': "al",
        'label': "审计日志",
        'columns': {
            "id": "主键",
            "action_type": "动作类型",
            "order_id": "订单",
            "operator": "操作者",
            "created_at": "时间",
        },
        'notes': "审计面,分析只读可用",
    },
    "session_metrics": {
        'domain': "shared",
        'table': "session_metrics",
        'database': "engine_db",
        'alias': "sm",
        'label': "会话指标",
        'columns': {
            "business_id": "租户",
            "resolution_status": "resolved_auto/未解决",
            "created_at": "时间",
        },
        'notes': "engine 本地库;查询必带 business_id 谓词",
    },
    "after_sale_tickets": {
        'domain': "shared",
        'table': "after_sale_tickets",
        'database': "engine_db",
        'alias': "t",
        'label': "售后工单",
        'columns': {
            "business_id": "租户",
            "status": "工单状态",
            "created_at": "时间",
        },
        'notes': "engine 本地库;查询必带 business_id 谓词",
    },
    "merchant_orders": {
        'domain': "trading",
        'table': "merchant_orders",
        'database': "merchant_db",
        'alias': "o",
        'label': "订单",
        'columns': {
            "order_id": "订单号",
            "customer_id": "客户",
            "status": "PAID/SHIPPED/DELIVERED/REFUNDED/CANCELLED",
            "total_amount": "金额",
            "created_at": "下单时间",
        },
        'notes': "有效成交口径:status NOT IN (REFUNDED, CANCELLED)",
    },
    "merchant_order_items": {
        'domain': "trading",
        'table': "merchant_order_items",
        'database': "merchant_db",
        'alias': "oi",
        'label': "订单明细",
        'columns': {
            "order_id": "→ merchant_orders.order_id",
            "spu_id": "商品编码(关联 spus.spu_code)",
            "quantity": "件数",
            "price": "成交价快照",
            "cost_at_purchase": "成交成本快照(NOT NULL)",
        },
        'notes': "销量 = SUM(quantity);GMV = SUM(quantity*price);成本求和不容 COALESCE",
    },
}
CARD_MAIN_ORDER: Final[tuple[str, ...]] = ('merchant_spus', 'merchant_skus', 'merchant_orders', 'merchant_order_items', 'merchant_product_reviews', 'merchant_customers', 'merchant_audit_logs')
CARD_SPECIAL_ORDER: Final[tuple[str, ...]] = ('promotions', 'promotion_redemptions', 'session_metrics', 'after_sale_tickets', 'user_coupons')
MAIN_CARD_TABLES: Final[dict[str, dict[str, object]]] = {
    "merchant_spus": {
        'columns': {
            "id": "uuid 主键",
            "spu_code": "商品编码(明细表关联键)",
            "title": "商品标题",
            "category": "品类",
            "brand": "品牌",
            "status": "ON_SALE/OFF_SALE",
        },
        'notes': "在售过滤 status='ON_SALE'",
    },
    "merchant_skus": {
        'columns': {
            "id": "uuid 主键",
            "spu_id": "→ merchant_spus.id",
            "price": "售价",
            "stock": "库存件数",
        },
        'notes': "展示价 = MIN(price);库存 = SUM(stock)",
    },
    "merchant_orders": {
        'columns': {
            "order_id": "订单号",
            "customer_id": "客户",
            "status": "PAID/SHIPPED/DELIVERED/REFUNDED/CANCELLED",
            "total_amount": "金额",
            "created_at": "下单时间",
        },
        'notes': "有效成交口径:status NOT IN (REFUNDED, CANCELLED)",
    },
    "merchant_order_items": {
        'columns': {
            "order_id": "→ merchant_orders.order_id",
            "spu_id": "商品编码(关联 spus.spu_code)",
            "quantity": "件数",
            "price": "成交价快照",
            "cost_at_purchase": "成交成本快照(NOT NULL)",
        },
        'notes': "销量 = SUM(quantity);GMV = SUM(quantity*price);成本求和不容 COALESCE",
    },
    "merchant_product_reviews": {
        'columns': {
            "id": "主键",
            "spu_id": "商品",
            "rating": "1-5 星",
            "content": "评语",
            "created_at": "时间",
        },
        'notes': "差评口径:rating <= 2",
    },
    "merchant_customers": {
        'columns': {
            "id": "主键",
            "customer_id": "客户编号",
            "member_level": "会员级",
        },
        'notes': "",
    },
    "merchant_audit_logs": {
        'columns': {
            "id": "主键",
            "action_type": "动作类型",
            "order_id": "订单",
            "operator": "操作者",
            "created_at": "时间",
        },
        'notes': "审计面,分析只读可用",
    },
}
SPECIAL_FAMILY_TABLES: Final[dict[str, dict[str, object]]] = {
    "promotions": {
        'columns': {
            "id": "主键",
            "name": "活动名",
        },
        'notes': "",
    },
    "promotion_redemptions": {
        'columns': {
            "promotion_id": "→ promotions.id",
            "order_id": "→ merchant_orders.order_id",
            "discount_amount": "优惠金额",
            "created_at": "核销时间",
        },
        'notes': "核销关联口径:真实归因,自然流量不计入",
    },
    "session_metrics": {
        'columns': {
            "business_id": "租户",
            "resolution_status": "resolved_auto/未解决",
            "created_at": "时间",
        },
        'notes': "engine 本地库;查询必带 business_id 谓词",
    },
    "after_sale_tickets": {
        'columns': {
            "business_id": "租户",
            "status": "工单状态",
            "created_at": "时间",
        },
        'notes': "engine 本地库;查询必带 business_id 谓词",
    },
    "user_coupons": {
        'columns': {
            "user_id": "客户ID(= merchant_customers.customer_id)",
            "promotion_id": "→ promotions.id",
            "status": "claimed/used",
            "claimed_at": "领取时间",
            "used_at": "核销时间",
        },
        'notes': "客户实体过滤",
    },
}

# --- 资金闸缺省(application/actions.yaml defaults)-------------------------
# 考古注记:历史六处分叉 50/100 —— 统一 50(收紧方向,ADR-0015 决策 4);
# 租户级显式覆写(nike=150/adidas=120)通道语义不变,本常量只钉缺省。
DEFAULT_REFUND_AUTO_APPROVAL_LIMIT: Final[float] = 50.0

__all__ = [
    "APPROVAL_ACTIONS",
    "CARD_MAIN_ORDER",
    "CARD_SPECIAL_ORDER",
    "CUSTOMER_ACTIONS",
    "DEFAULT_REFUND_AUTO_APPROVAL_LIMIT",
    "ENGINE_HANDLED_ACTIONS",
    "MAIN_CARD_TABLES",
    "ONTOLOGY_ENTITIES",
    "OPERATOR_ACTIONS",
    "SPECIAL_FAMILY_TABLES",
    "SPI_ACTIONS",
    "STAFF_REVIEW_ACTIONS",
    "TS_GHOST_ACTIONS",
]
