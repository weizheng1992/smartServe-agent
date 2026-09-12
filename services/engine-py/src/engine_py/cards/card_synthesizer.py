"""富卡片合成器 — 镜像 cards/cardSynthesizer.ts(Type-Safe 卡片家族合成)。"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

_AMOUNT_STRIP_RE = re.compile(r"[^0-9.]")

# ── 场景化快捷回复(ADR-0001,2026-09-12)───────────────────────────────
# 每个按钮背后必须有真实能力兜底(死按钮禁令 = 2.6.8 数据诚实铁律延伸到
# UI 交互层);「热销」类文案自 ADR-0002 起改为数据条件禁令——有真销量
# 聚合兜底的专用入口可挂,品类 chip 自身仍严禁热度词。
# 场景键为意图 id(呈现层自有,意图注册表零改动,ADR-0001 Q6=A)。
_SCENE_REFUND_INTENTS = frozenset({"refund", "order_return"})
_GUIDE_INTENT = "shopping_guide"
# 品类快捷区总上限 8 = 热销入口 1 + 品类 7(ADR-0002 Q7)
_GUIDE_CHIP_CATEGORY_LIMIT = 7


def _intent_ids(intents: list[dict] | None) -> set[str]:
    """本轮已分类意图 id 集(state.intents 条目形如 {"intent": ..., "confidence": ...})。"""
    return {it.get("intent") for it in (intents or []) if isinstance(it, dict)}

_QUICK_REPLY_SETS: dict[str, list[dict]] = {
    # 退款/售后场景(ADR-0001 Q2):用户已在退款流程,「申请退款」撤下;
    # 「查询未发货的订单」由 list_user_orders 的 shippingStatus 过滤兜底。
    "refund": [
        {"label": "🧾 查询最近的订单", "action": "send_message", "payload": {"text": "查询我最近的订单"}},
        {"label": "🚚 查询未发货的订单", "action": "send_message", "payload": {"text": "查询我未发货的订单"}},
        {"label": "📷 上传商品瑕疵照片", "action": "trigger_upload", "payload": {"prompt": "上传商品照片核验"}},
        {"label": "🎧 呼叫人工客服", "action": "send_message", "payload": {"text": "转人工"}},
    ],
    # 兜底通用组(ADR-0001 Q5):旧「查询物流进度」并入订单查询——同一意图
    # 同一出口,订单回复自带物流/时间线,不留两个按钮挤一个门。
    "default": [
        {"label": "📦 查询我的订单", "action": "send_message", "payload": {"text": "查询我最近的订单"}},
        {"label": "🛍️ 逛逛商城", "action": "send_message", "payload": {"text": "看看商城有什么商品"}},
        {"label": "💰 申请退款", "action": "send_message", "payload": {"text": "我想申请退款"}},
        {"label": "🎧 呼叫人工客服", "action": "send_message", "payload": {"text": "转人工"}},
    ],
}


def _scene_quick_replies(options: dict) -> dict:
    """按本轮已分类意图挑场景组(ADR-0001 Q1);品类 chips 只认真货架盘点
    数据,盘点空退通用组,严禁编造品类(ADR-0001 Q3)。"""
    intent_ids = _intent_ids(options.get("intents"))
    if intent_ids & _SCENE_REFUND_INTENTS:
        return {"title": "您可能需要：", "options": list(_QUICK_REPLY_SETS["refund"])}
    if _GUIDE_INTENT in intent_ids:
        categories = [c for c in (options.get("shelfCategories") or []) if c.get("category")][:_GUIDE_CHIP_CATEGORY_LIMIT]
        if categories:
            return {
                "title": "在售品类，点按直达：",
                "options": [
                    # ADR-0002 Q4/Q7:热销入口置顶——点击走真销量排行
                    # (queryProductRanking 商户真订单聚合);品类 chip 自身
                    # 严禁挂热度词,「热销」二字由真数据兜底(数据条件禁令)。
                    # 「热销」裸词会被导购词表截获(实弹验证),点击文本必须带排行/销量语义
                    {"label": "🔥 热销商品", "action": "send_message", "payload": {"text": "按销量查一下热销商品排行"}},
                    *[
                        {
                            "label": f"🏷️ {c['category']}({c.get('spuCount', 0)}款)",
                            "action": "send_message",
                            "payload": {"text": f"看看{c['category']}有什么商品"},
                        }
                        for c in categories
                    ],
                ],
            }
    return {"title": "您可能需要：", "options": list(_QUICK_REPLY_SETS["default"])}


def _parse_amount(raw: Any) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(_AMOUNT_STRIP_RE.sub("", raw)) or 0
        except ValueError:
            return 0
    return 0


class CardSynthesizer:
    @staticmethod
    async def fetch_shelf_categories(intents: list[dict] | None, thread_id: str | None = None) -> list[dict]:
        """购物意图轮实查真货架品类盘点(ADR-0001 Q3,喂给品类 chips)。

        非购物轮零查库;盘点不可达诚实空(该轮不挂品类 chips),严禁静态
        假目录兜底。运行时模块属性查表,禁导入期绑定(测试桩点)。"""
        if _GUIDE_INTENT not in _intent_ids(intents):
            return []
        from ..tools_registry.mall_domain import MallDomainService

        try:
            return await MallDomainService.get_shelf_overview()
        except Exception as err:
            print(f"[CardSynthesizer] 品类盘点不可达,该轮不挂品类 chips threadId={thread_id}: {err}")
            return []

    @staticmethod
    def synthesize_skeleton_cards(options: dict) -> list[dict]:
        """流式骨架卡片(Streaming Hydration Skeletons)。"""
        skeletons: list[dict] = []
        task_plan = options.get("taskPlan") or {}
        intents = options.get("intents") or []

        subtasks = task_plan.get("subtasks") or []
        if subtasks:
            for st in subtasks:
                st_id = st.get("id") or ""
                if "order" in st_id or "status" in st_id:
                    skeletons.append(
                        {
                            "id": f"skel_order_{st_id}",
                            "type": "order_card",
                            "hydrationState": "skeleton",
                            "data": {"orderId": "ORD-LOADING...", "status": "加载中...", "totalAmount": 0},
                        }
                    )
                elif "refund" in st_id or "step" in st_id:
                    skeletons.append(
                        {
                            "id": f"skel_step_{st_id}",
                            "type": "step_progress",
                            "hydrationState": "skeleton",
                            "data": {
                                "title": "业务流程加载中...",
                                "currentStep": 0,
                                "totalSteps": 3,
                                "steps": [
                                    {"stepIndex": 0, "title": "提交申请", "status": "completed"},
                                    {"stepIndex": 1, "title": "审核处理", "status": "current"},
                                    {"stepIndex": 2, "title": "完成确认", "status": "upcoming"},
                                ],
                            },
                        }
                    )
        elif intents:
            for it in intents:
                if it.get("intent") == "order_status":
                    skeletons.append(
                        {
                            "id": f"skel_intent_order_{it.get('intent')}",
                            "type": "order_card",
                            "hydrationState": "skeleton",
                            "data": {"orderId": "ORD-LOADING...", "status": "查询中...", "totalAmount": 0},
                        }
                    )
        return skeletons

    @staticmethod
    def synthesize_cards(options: dict) -> list[dict]:
        cards: list[dict] = []
        task_plan = options.get("taskPlan") or {}
        damage_assessment = options.get("damageAssessment")

        # 1. 破损定责卡
        if damage_assessment:
            cards.append({"type": "damage_assessment", "data": damage_assessment})

        for st in task_plan.get("subtasks") or []:
            raw_result = st.get("result") or {}
            result = raw_result.get("output") if isinstance(raw_result.get("output"), dict) else None
            result = result or (raw_result if isinstance(raw_result, dict) else None)
            if not result or result.get("error"):
                continue

            order_id = result.get("orderId") if isinstance(result.get("orderId"), str) else None
            status = result.get("status") if isinstance(result.get("status"), str) else None
            carrier = result.get("carrier") if isinstance(result.get("carrier"), str) else None
            tracking_number = (
                result.get("trackingNumber") if isinstance(result.get("trackingNumber"), str) else None
            )

            # 2. 订单卡 / 物流轨迹卡(getOrderStatus / listUserOrders)
            orders_list: list[dict] = result.get("orders") if isinstance(result.get("orders"), list) else []
            if not orders_list and order_id and (status or carrier or tracking_number):
                orders_list = [result]

            synthesized_order_cards: list[dict] = []
            for ord_row in orders_list:
                ord_id = ord_row.get("orderId") or ord_row.get("order_id")
                ord_status = ord_row.get("status") or "已确认"
                ord_carrier = ord_row.get("carrier") or "标准快递"
                ord_tracking = ord_row.get("trackingNumber") or ord_row.get("tracking_number") or "暂无运单号"
                if not ord_id:
                    continue
                order_card = {
                    "orderId": ord_id,
                    "status": ord_status,
                    "totalAmount": _parse_amount(
                        ord_row.get("totalAmount") or ord_row.get("total_amount") or ord_row.get("amount")
                    ),
                    "currency": ord_row.get("currency") or "USD",
                    "carrier": ord_carrier,
                    "trackingNumber": ord_tracking,
                    "createdAt": ord_row.get("createdAt") or ord_row.get("created_at")
                    or _dt.datetime.now().isoformat(),
                    "actions": [
                        {"label": "查看物流轨迹", "action": "track_order", "payload": {"orderId": ord_id}},
                        {"label": "申请退款", "action": "request_refund", "payload": {"orderId": ord_id}},
                    ],
                }
                synthesized_order_cards.append(order_card)

            if synthesized_order_cards:
                if len(synthesized_order_cards) == 1:
                    cards.append({"type": "order_card", "data": synthesized_order_cards[0]})
                else:
                    cards.append(
                        {
                            "type": "order_picker",
                            "data": {
                                "title": f"为您查询到 {len(synthesized_order_cards)} 笔订单记录",
                                "totalCount": len(synthesized_order_cards),
                                "orders": synthesized_order_cards,
                            },
                        }
                    )

                if len(synthesized_order_cards) == 1:
                    single_order = synthesized_order_cards[0]
                    if single_order["trackingNumber"] or single_order["carrier"]:
                        raw_timeline = (
                            orders_list[0].get("timeline")
                            if isinstance(orders_list[0].get("timeline"), list)
                            else None
                        )
                        if not raw_timeline:
                            raw_timeline = [
                                {
                                    "time": _dt.datetime.now().isoformat().replace("T", " ")[:16],
                                    "location": f"{single_order['carrier'] or '顺丰速运'} 派送中",
                                    "description": f"包裹正在运送中，状态：{single_order['status']}",
                                    "status": "in_transit",
                                },
                                {
                                    "time": "订单发货",
                                    "location": "发货仓库",
                                    "description": "商品已完成质检并打包装箱出库",
                                    "status": "completed",
                                },
                            ]
                        timeline_card = {
                            "trackingNumber": single_order["trackingNumber"] or "",
                            "carrier": single_order["carrier"] or "顺丰速运",
                            "currentStatus": single_order["status"],
                            "estimatedDelivery": orders_list[0].get("estimatedDelivery")
                            or orders_list[0].get("estimated_delivery")
                            or "预计 1-3 个工作日内送达",
                            "timeline": raw_timeline,
                        }
                        cards.append({"type": "tracking_timeline", "data": timeline_card})

            # 3. 退款核签卡(processRefund)
            st_id = st.get("id") or ""
            is_refund_task = (
                "refund" in st_id
                or "refund" in (st.get("description") or "").lower()
                or result.get("refundAmount") is not None
                or result.get("refundId") is not None
            )
            if is_refund_task and order_id:
                refund_card = {
                    "orderId": order_id,
                    "refundAmount": _parse_amount(result.get("refundAmount") or result.get("amount")),
                    "currency": result.get("currency") or "USD",
                    "refundReason": result.get("reason") or "用户申请售后退款",
                    "refundMethod": "原路返回支付账户 (Original Payment Method)",
                    "status": (
                        "pending_confirmation"
                        if result.get("waitingForApproval")
                        else "approved"
                        if result.get("success")
                        else "submitted"
                    ),
                    "requiresApproval": bool(result.get("waitingForApproval")),
                }
                cards.append({"type": "refund_confirmation", "data": refund_card})

            # 4. 商品排行卡(queryProductRanking)
            # 判定只认排行签名(rankingMetric/步骤语义)——严禁「products 非空
            # 即排行卡」:searchProducts 工具结果的键同样叫 products,条目是
            # 检索形(无 totalGmv/grossProfit),误装后前端读缺失字段抛
            # toLocaleString TypeError 白屏,且给搜索结果盖假「GMV 排行」头衔。
            is_ranking_task = (
                "ranking" in st_id
                or "ranking" in (st.get("description") or "").lower()
                or result.get("rankingMetric") is not None
            )
            if is_ranking_task and isinstance(result.get("products"), list):
                ranking_card = {
                    "rankingMetric": result.get("rankingMetric") or "gmv",
                    "metricLabel": result.get("metricLabel") or "总销售额 (GMV)",
                    "metricUnit": result.get("metricUnit") or "元",
                    "itemCount": int(result.get("itemCount") or len(result["products"])),
                    "summary": result.get("summary"),
                    "products": result["products"],
                }
                cards.append({"type": "product_ranking", "data": ranking_card})

            # 5. 步进卡(StepProgress)
            step_progress = result.get("stepProgress") or result.get("workflowSteps")
            if step_progress and isinstance(step_progress.get("steps"), list):
                cards.append(
                    {
                        "type": "step_progress",
                        "hydrationState": "ready",
                        "data": {
                            "ticketId": step_progress.get("ticketId") or result.get("ticketId"),
                            "orderId": step_progress.get("orderId") or order_id,
                            "title": step_progress.get("title") or "业务售后流转追踪",
                            "currentStep": step_progress.get("currentStep", 0),
                            "totalSteps": step_progress.get("totalSteps") or len(step_progress["steps"]),
                            "steps": step_progress["steps"],
                            "settledSummary": step_progress.get("settledSummary"),
                        },
                    }
                )

            # 6. 交互式商品卡(InteractiveProduct)
            interactive_product = result.get("interactiveProduct") or result.get("productDetail")
            if (
                interactive_product
                and isinstance(interactive_product.get("skus"), list)
                and interactive_product["skus"]
            ):
                skus = interactive_product["skus"]
                cards.append(
                    {
                        "type": "interactive_product",
                        "hydrationState": "ready",
                        "data": {
                            "productId": interactive_product.get("productId") or "PROD-DEFAULT",
                            "title": interactive_product.get("title"),
                            "subtitle": interactive_product.get("subtitle"),
                            "imageUrl": interactive_product.get("imageUrl"),
                            "basePrice": interactive_product.get("basePrice")
                            or (skus[0].get("price") if skus else 0),
                            "skus": skus,
                            "selectedSkuId": interactive_product.get("selectedSkuId")
                            or (skus[0].get("skuId") if skus else None),
                            "selectedQuantity": interactive_product.get("selectedQuantity") or 1,
                            "actions": interactive_product.get("actions"),
                        },
                    }
                )

        # 快捷回复胶囊(ADR-0001 Q4):域卡片优先作基座(原 run_agent
        # short-circuit 语义收编进合成器),排行卡优先挂指标消歧组(2.6.12
        # 契约),其余按本轮意图出场景组,统一追加在消息尾部。
        # 技能自带的 quick_replies(如破损照片消歧组)是更具体的场景行:
        # first-wins 原样保留,严禁一屏两条胶囊。
        existing_cards = options.get("existingCards") or []
        base_cards = list(existing_cards) if existing_cards else cards
        if any(c.get("type") == "quick_replies" for c in base_cards):
            return base_cards
        if any(
            c.get("type") == "product_ranking"
            and (c.get("data") or {}).get("rankingMetric") in ("gmv", "volume", "stock_risk")
            for c in base_cards
        ):
            # ADR-0002:毛利/毛利率口径已随成本数据缺位移除,消歧组 5→3——
            # 挂着算不了的口径就是死按钮。
            quick_replies = {
                "title": "您也可以一键切换其他统计口径：",
                "options": [
                    {"label": "💰 按总销售额 (GMV)", "action": "send_message", "payload": {"text": "按总销售额最高的热销商品排行 Top 5"}},
                    {"label": "📦 按出货销量件数", "action": "send_message", "payload": {"text": "按出货销量最高的热销商品排行 Top 5"}},
                    {"label": "⚠️ 排查滞销库存", "action": "send_message", "payload": {"text": "排查在售商品的滞销库存风险"}},
                ],
            }
        else:
            quick_replies = _scene_quick_replies(options)
        base_cards.append({"type": "quick_replies", "data": quick_replies})
        return base_cards
