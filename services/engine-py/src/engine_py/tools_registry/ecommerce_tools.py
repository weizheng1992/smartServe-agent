"""电商工具定义与注册 — 镜像 tools/src/ecommerce.tools.ts(19 工具)。

takeScreenshot 截图工具(TS 走 puppeteer-core)以 TODO 桩注册,
Phase 1b 接入 playwright 后替换。schema 以 JSON-Schema 风式 dict 描述
(运行时按需校验;影子对比只关心工具名与入参出参行为)。
"""

from __future__ import annotations

from . import ToolDefinition, register_tool
from .mall_domain import MallDomainService
from .order_domain import OrderDomainService


async def _get_order_status(args: dict):
    return await OrderDomainService.get_order_status(args["orderId"], args.get("threadId"))


async def _process_refund(args: dict):
    return await OrderDomainService.process_refund(
        args["orderId"], args["reason"], args.get("threadId"), args.get("amount")
    )


async def _list_user_orders(args: dict):
    return await OrderDomainService.list_user_orders(
        args.get("threadId"),
        args.get("userId"),
        args.get("businessId") or args.get("tenantId"),
        args.get("shippingStatus"),
    )


async def _change_shipping_address(args: dict):
    return await OrderDomainService.change_shipping_address(
        args["orderId"], args["newAddress"], args.get("threadId"), args.get("isApproved")
    )


async def _generate_invoice(args: dict):
    return await OrderDomainService.generate_invoice(args["orderId"], args.get("threadId"))


async def _record_user_preference(args: dict):
    return await OrderDomainService.record_user_preference(
        args["preferenceType"], args["preferenceValue"], args.get("threadId")
    )


# createOrder 工具注册面已摘除(多意图一期,2026-09-12):它写 engine 本地
# demo orders 表、硬编 status='shipped' 并编造顺丰运单号,是假单工具 —— 聊天
# 下单诉求由 planner 深规划规则 8 引导加购+购物车卡结算,严禁经此造假单。
# OrderDomainService.create_order 方法保留供测试/演示种子使用。


async def _query_product_ranking(args: dict):
    return await OrderDomainService.query_product_ranking(args)


async def _get_user_addresses(args: dict):
    return await MallDomainService.get_user_addresses(args.get("userId"), None, args.get("threadId"))


async def _save_user_address(args: dict):
    return await MallDomainService.save_user_address(args)


async def _checkout_cart(args: dict):
    """真·聊天下单(遗留二期):购物车 → 商户真单,与商城页同一账本。"""
    return await MallDomainService.checkout_user_cart(args)


async def _set_default_address(args: dict):
    """设默认收货地址(2026-09-15 S8 能力补齐)。"""
    return await MallDomainService.set_default_address(args)


async def _delete_user_address(args: dict):
    """删除收货地址(2026-09-15 能力补齐)。"""
    return await MallDomainService.delete_user_address(args)


async def _query_product_skus(args: dict):
    return await MallDomainService.query_product_skus(args)


async def _query_package_tracking(args: dict):
    return await MallDomainService.query_package_tracking(args)


async def _query_product_reviews(args: dict):
    return await MallDomainService.query_product_reviews(args)


async def _apply_after_sale(args: dict):
    return await MallDomainService.apply_after_sale(args)


async def _search_products(args: dict):
    return await MallDomainService.search_products(args)


async def _compare_products(args: dict):
    return await MallDomainService.compare_products(args)


async def _add_to_cart(args: dict):
    return await MallDomainService.add_to_cart(args)


async def _get_cart_summary(args: dict):
    return await MallDomainService.get_cart_summary(args)


async def _update_cart_item(args: dict):
    return await MallDomainService.update_cart_item(args)


async def _take_screenshot(args: dict):
    # TODO(Phase 1b): 接入 playwright(等价 TS puppeteer-core 截图工具,5000ms 超时)
    return {"error": "takeScreenshot 尚未在 engine-py 移植(TODO Phase 1b playwright)"}


register_tool(
    ToolDefinition(
        name="getOrderStatus",
        description=(
            "Get the status of a specific order by order ID. Secured: Only allowed if the order "
            "belongs to the currently logged-in customer."
        ),
        schema={"type": "object", "properties": {"orderId": {"type": "string"}}},
        execute=_get_order_status,
    )
)
register_tool(
    ToolDefinition(
        name="processRefund",
        description=(
            "Process a refund for an order. Secured: Only allowed if the order belongs to the "
            "currently logged-in customer."
        ),
        schema={
            "type": "object",
            "properties": {
                "orderId": {"type": "string"},
                "reason": {"type": "string"},
                "evidenceImageUrls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional evidence photo URLs uploaded this turn. Auto-attached by the "
                        "engine; surfaces to the human approver via the approval payload."
                    ),
                },
            },
        },
        execute=_process_refund,
    )
)
register_tool(
    ToolDefinition(
        name="listUserOrders",
        description=(
            "List all recent orders and tracking status for the current customer. Supports an "
            "optional shippingStatus filter: UNSHIPPED (not shipped yet, incl. paid awaiting "
            "shipment), SHIPPED, DELIVERED."
        ),
        schema={
            "type": "object",
            "properties": {
                "shippingStatus": {
                    "type": "string",
                    "enum": ["UNSHIPPED", "SHIPPED", "DELIVERED"],
                    "description": "Optional filter. UNSHIPPED = still awaiting shipment (excludes shipped/delivered/refunded/cancelled).",
                }
            },
        },
        execute=_list_user_orders,
    )
)
register_tool(
    ToolDefinition(
        name="changeShippingAddress",
        description=(
            "Modify the shipping address of an order before it gets shipped. Secured: Only allowed "
            "if the order belongs to the currently logged-in customer."
        ),
        schema={
            "type": "object",
            "properties": {"orderId": {"type": "string"}, "newAddress": {"type": "string"}},
        },
        execute=_change_shipping_address,
    )
)
register_tool(
    ToolDefinition(
        name="generateInvoice",
        description=(
            "Generate a structured electronic tax invoice for a completed order. Secured: Only "
            "allowed if the order belongs to the currently logged-in customer."
        ),
        schema={"type": "object", "properties": {"orderId": {"type": "string"}}},
        execute=_generate_invoice,
    )
)
register_tool(
    ToolDefinition(
        name="recordUserPreference",
        description=(
            "Record specific consumer preferences of the current customer (such as clothing size, "
            "favorite color, stylistic preference, material allergies/restrictions) into long-term "
            "memories for future search and sizing recommendation."
        ),
        schema={
            "type": "object",
            "properties": {
                "preferenceType": {"type": "string", "enum": ["size", "color", "brand", "style", "material", "other"]},
                "preferenceValue": {"type": "string"},
            },
        },
        execute=_record_user_preference,
    )
)
register_tool(
    ToolDefinition(
        name="queryProductRanking",
        description=(
            "Query and rank mall products across multi-dimensional metrics (GMV sales revenue, "
            "shipment volume, gross profit, margin rate, or stock risk) with tenant isolation and "
            "manager ownership security."
        ),
        schema={
            "type": "object",
            "properties": {
                "rankingMetric": {"type": "string"},
                "managerOnly": {"type": "boolean"},
                "category": {"type": "string"},
                "limit": {"type": "number"},
            },
        },
        execute=_query_product_ranking,
    )
)
register_tool(
    ToolDefinition(
        name="getUserAddresses",
        description=(
            "Get all saved recipient delivery addresses for the current user, including tags and "
            "default flags."
        ),
        schema={"type": "object", "properties": {"userId": {"type": "string"}}},
        execute=_get_user_addresses,
    )
)
register_tool(
    ToolDefinition(
        name="saveUserAddress",
        description="Save or create a new delivery address for this customer.",
        schema={
            "type": "object",
            "properties": {
                "receiverName": {"type": "string"},
                "receiverPhone": {"type": "string"},
                "province": {"type": "string"},
                "city": {"type": "string"},
                "district": {"type": "string"},
                "detailAddress": {"type": "string"},
                "tag": {"type": "string", "enum": ["home", "company", "school", "other"]},
                "isDefault": {"type": "boolean"},
            },
        },
        execute=_save_user_address,
    )
)
register_tool(
    ToolDefinition(
        name="checkoutCart",
        description=(
            "Place a REAL order from the customer's current shopping cart: resolves real merchant SKUs "
            "(SPU lines settle at the current cheapest in-stock SKU), checks and deducts stock, snapshots "
            "cost, and binds the shipping address (explicit address, or the customer's default address book "
            "entry; fails honestly asking for an address when none exists). Auto-resolves user context. "
            "All-or-nothing: any unavailable cart line cancels the whole order."
        ),
        schema={
            "type": "object",
            "properties": {
                "userId": {"type": "string"},
                "threadId": {"type": "string"},
                "shippingAddress": {"type": "object", "description": "Optional explicit address {fullAddress, recipientName, phone} or plain string"},
            },
        },
        execute=_checkout_cart,
    )
)
register_tool(
    ToolDefinition(
        name="deleteUserAddress",
        description="Delete one of the customer's saved delivery addresses (matches by recipient name or address substring).",
        schema={
            "type": "object",
            "properties": {
                "userId": {"type": "string"},
                "threadId": {"type": "string"},
                "receiverName": {"type": "string"},
                "fullAddress": {"type": "string"},
            },
        },
        execute=_delete_user_address,
    )
)
register_tool(
    ToolDefinition(
        name="setDefaultAddress",
        description="Set one of the customer's saved delivery addresses as the default (matches by address id or recipient name from conversation context).",
        schema={
            "type": "object",
            "properties": {
                "userId": {"type": "string"},
                "threadId": {"type": "string"},
                "addressId": {"type": "string"},
                "receiverName": {"type": "string"},
            },
        },
        execute=_set_default_address,
    )
)
register_tool(
    ToolDefinition(
        name="queryProductSkus",
        description="Query detailed product SKU specifications (color, size, edition) along with real-time stock and prices.",
        schema={
            "type": "object",
            "properties": {
                "productId": {"type": "string"},
                "color": {"type": "string"},
                "size": {"type": "string"},
                "inStockOnly": {"type": "boolean"},
            },
        },
        execute=_query_product_skus,
    )
)
register_tool(
    ToolDefinition(
        name="queryPackageTracking",
        description="Query real-time parcel delivery tracking status, courier details, and chronological timeline nodes.",
        schema={
            "type": "object",
            "properties": {"orderId": {"type": "string"}, "trackingNumber": {"type": "string"}},
        },
        execute=_query_package_tracking,
    )
)
register_tool(
    ToolDefinition(
        name="queryProductReviews",
        description="Query customer feedback, ratings, sentiment summary, and sizing/fit consensus for a product.",
        schema={
            "type": "object",
            "properties": {
                "productId": {"type": "string"},
                "fitFeedback": {"type": "string", "enum": ["true_to_size", "runs_small", "runs_large"]},
                "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
                "limit": {"type": "number"},
            },
        },
        execute=_query_product_reviews,
    )
)
register_tool(
    ToolDefinition(
        name="applyAfterSale",
        description="Submit an after-sale customer service ticket (refund only, return and refund, or exchange).",
        schema={
            "type": "object",
            "properties": {
                "orderId": {"type": "string"},
                "type": {"type": "string", "enum": ["refund_only", "return_and_refund", "exchange"]},
                "reason": {"type": "string", "enum": ["wrong_size", "quality_issue", "not_as_described", "no_reason_7d"]},
                "reasonDescription": {"type": "string"},
                "refundAmount": {"type": "number"},
                "evidenceImageUrls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional evidence photo URLs uploaded this turn. Normally auto-attached "
                        "by the engine from the conversation's uploaded images — do not invent URLs."
                    ),
                },
            },
        },
        execute=_apply_after_sale,
    )
)
register_tool(
    ToolDefinition(
        name="searchProducts",
        description="Search products by keywords, category, or price range for shopping recommendations.",
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "category": {"type": "string"},
                "maxPrice": {"type": "number"},
                "limit": {"type": "number"},
            },
        },
        execute=_search_products,
    )
)
register_tool(
    ToolDefinition(
        name="compareProducts",
        description="Compare detailed features, specs, and prices across multiple selected product IDs.",
        schema={"type": "object", "properties": {"productIds": {"type": "array", "items": {"type": "string"}}}},
        execute=_compare_products,
    )
)
register_tool(
    ToolDefinition(
        name="addToCart",
        description="Add a product SKU to user shopping cart with quantity and options.",
        schema={
            "type": "object",
            "properties": {
                "skuId": {"type": "string"},
                "quantity": {"type": "number"},
                "title": {"type": "string"},
                "price": {"type": "number"},
                "spec": {"type": "string"},
            },
        },
        execute=_add_to_cart,
    )
)
register_tool(
    ToolDefinition(
        name="getCartSummary",
        description="Get current user shopping cart items, total quantity, and calculated amount.",
        schema={"type": "object", "properties": {}},
        execute=_get_cart_summary,
    )
)
register_tool(
    ToolDefinition(
        name="updateCartItem",
        description="Update quantity of an item in shopping cart, or remove if quantity is 0.",
        schema={
            "type": "object",
            "properties": {"skuId": {"type": "string"}, "quantity": {"type": "number"}},
        },
        execute=_update_cart_item,
    )
)
register_tool(
    ToolDefinition(
        name="takeScreenshot",
        description="Take a screenshot of a web page for visual verification.",
        schema={"type": "object", "properties": {"url": {"type": "string"}}},
        execute=_take_screenshot,
    )
)
