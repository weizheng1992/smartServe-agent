"""富卡片合成器 — 镜像 cards/cardSynthesizer.ts(Type-Safe 卡片家族合成)。"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

_AMOUNT_STRIP_RE = re.compile(r"[^0-9.]")


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
            is_ranking_task = (
                "ranking" in st_id
                or "ranking" in (st.get("description") or "").lower()
                or result.get("rankingMetric") is not None
                or (isinstance(result.get("products"), list) and result.get("products"))
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

        # 快捷回复胶囊(排行卡优先挂指标消歧组)
        has_ranking_card = any(c.get("type") == "product_ranking" for c in cards)
        if has_ranking_card:
            quick_replies = {
                "title": "您也可以一键切换其他统计口径：",
                "options": [
                    {"label": "💰 按总销售额 (GMV)", "action": "send_message", "payload": {"text": "按总销售额最高查询我负责的商品 Top 5"}},
                    {"label": "📦 按出货销量件数", "action": "send_message", "payload": {"text": "按出货销量最高查询我负责的商品 Top 5"}},
                    {"label": "📈 按净毛利润金额", "action": "send_message", "payload": {"text": "按净毛利润最高查询我负责的商品 Top 5"}},
                    {"label": "🎯 按单品毛利率 %", "action": "send_message", "payload": {"text": "按毛利率最高查询我负责的商品 Top 5"}},
                    {"label": "⚠️ 排查滞销库存", "action": "send_message", "payload": {"text": "排查我负责的滞销库存商品"}},
                ],
            }
        else:
            quick_replies = {
                "title": "您可能需要：",
                "options": [
                    {"label": "📦 查询物流进度", "action": "send_message", "payload": {"text": "帮我查一下最新物流发货进度"}},
                    {"label": "💰 申请退款服务", "action": "send_message", "payload": {"text": "我想申请退款"}},
                    {"label": "📷 上传商品瑕疵照片", "action": "trigger_upload", "payload": {"prompt": "上传商品照片核验"}},
                    {"label": "🎧 呼叫人工客服", "action": "send_message", "payload": {"text": "转人工"}},
                ],
            }
        cards.append({"type": "quick_replies", "data": quick_replies})
        return cards
