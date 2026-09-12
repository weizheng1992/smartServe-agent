"""售后退款 + 极速改地址技能 — 镜像 orderRefundSkill.ts / orderAddressModificationSkill.ts。"""

from __future__ import annotations

import re
import uuid

from .base_skill import BaseSkill


class OrderRefundSkill(BaseSkill):
    metadata = {
        "id": "skill_order_refund",
        "name": "售后退款与理赔 SOP",
        "description": "支持退款时效校验、多模态破损阶梯赔付计算、HITL 高危金额安全门禁拦截与凭证核签",
        "category": "after_sale",
        "triggerIntents": ["ORDER_RETURN", "ORDER_CANCEL", "refund", "process_refund"],
        "requiredTools": ["getOrderDetail", "executeOrderAction"],
        "requiresApproval": True,
        "approvalThresholdAmount": 50,
        "version": "1.0.0",
    }

    # 与 triage REFUND_KEYWORDS_RE 对齐的文本兜底(仅用于动作嗅探/无槽位匹配,
    # fast-track 上下文必带 activeIntent,此正则在该路径不生效)
    _FALLBACK_RE = re.compile(r"(?:退款|退货|退钱|退单|不想要了|破损|瑕疵)", re.IGNORECASE)

    def can_handle(self, context: dict) -> bool:
        if super().can_handle(context):
            return True
        user_input = (context.get("input") or "").lower()
        return bool(self._FALLBACK_RE.search(user_input))

    async def execute(self, context: dict) -> dict:
        slots = context.get("slots") or {}
        order_id = slots.get("orderId") or ""
        reason = slots.get("reason") or slots.get("returnReason") or "客户申请退款"

        if not order_id:
            return {
                "success": False,
                "skillId": self.metadata["id"],
                "output": "申请退款需要提供订单编号，请补充您的订单号。",
                "error": "Missing required slot: orderId",
            }

        spi_client = await self.get_spi_client(context.get("tenantId", "ecommerce"))
        order = await spi_client.get_order_detail(
            {
                "orderId": order_id,
                "userId": context.get("userId"),
                "threadId": context.get("threadId"),
                "tenantId": context.get("tenantId", "ecommerce"),
            }
        )
        if not order:
            return {
                "success": False,
                "skillId": self.metadata["id"],
                "output": f"未查询到订单号 [{order_id}]，请核对后重试。",
                "error": f"Order {order_id} not found",
            }

        try:
            total_amount_num = float(order.get("totalAmount") or 0)
        except (TypeError, ValueError):
            total_amount_num = 0.0
        try:
            requested_amount = float(slots.get("refundAmount") or order.get("totalAmount")) or total_amount_num
        except (TypeError, ValueError):
            requested_amount = total_amount_num

        # Step 2: HITL 安全门禁(动态租户阈值)
        threshold = await self.get_effective_approval_threshold(context.get("tenantId", "ecommerce"))
        is_approved = bool((context.get("extra") or {}).get("isApproved"))

        if requested_amount > threshold and not is_approved:
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": (
                    f"您的退款申请金额为 ¥{requested_amount:.2f}（超过系统免审额度 ¥{threshold:.0f}），"
                    "已为您提交至人工客服复核，请稍候。"
                ),
                "nextAction": "require_approval",
                "extra": {
                    "orderContext": {
                        "targetOrderId": order_id,
                        "actionType": "refund",
                        "orderStatus": order.get("status"),
                    }
                },
                "approvalPayload": {
                    "actionType": "processRefund",
                    "amount": requested_amount,
                    "reason": reason,
                    "details": {
                        "orderId": order_id,
                        "totalAmount": order.get("totalAmount"),
                        "tenantId": context.get("tenantId"),
                        "userId": context.get("userId"),
                    },
                },
            }

        # Step 3: 执行退款动作(threadId 透传:process_refund 靠它解析归属用户)
        action_result = await spi_client.execute_order_action(
            {
                "actionType": "REQUEST_REFUND",
                "orderId": order_id,
                "userId": context.get("userId"),
                "threadId": context.get("threadId"),
                "refundAmount": requested_amount,
                "reason": reason,
                "idempotencyKey": str(uuid.uuid4()),
                "tenantId": context.get("tenantId", "ecommerce"),
            }
        )
        if not action_result.get("success"):
            return {
                "success": False,
                "skillId": self.metadata["id"],
                "output": f"订单 [{order_id}] 退款申请失败: {action_result.get('message') or '系统繁忙，请联系客服'}",
                "error": action_result.get("message"),
            }

        cards = [
            {
                "type": "refund_confirmation",
                "data": {
                    "orderId": order.get("orderId"),
                    "refundAmount": requested_amount,
                    "currency": "CNY",
                    "refundReason": reason,
                    "refundMethod": "ORIGINAL_PAYMENT",
                    "status": "approved",
                },
            }
        ]
        return {
            "success": True,
            "skillId": self.metadata["id"],
            "output": (
                f"已成功为您办理订单 [{order_id}] 的退款申请，退款金额 ¥{requested_amount:.2f} "
                "将在 1-3 个工作日内原路退回至您的支付账户。"
            ),
            "cards": cards,
            "nextAction": "finish",
            "extra": {
                "orderContext": {
                    "targetOrderId": order_id,
                    "orderStatus": "REFUNDED",
                    "actionType": "refund",
                }
            },
        }


class OrderAddressModificationSkill(BaseSkill):
    metadata = {
        "id": "skill_order_address_modification",
        "name": "极速改地址 SOP",
        "description": "校验订单履约状态并执行地址变更，支持三级地址合规格式化与变更卡片渲染",
        "category": "after_sale",
        "triggerIntents": ["ORDER_MODIFY_ADDRESS", "modify_address", "order_modify_address"],
        "requiredTools": ["getOrderDetail", "executeOrderAction"],
        "version": "1.0.0",
    }

    # 同上:仅用于动作嗅探的文本兜底
    _FALLBACK_RE = re.compile(r"(?:改地址|修改地址|更改地址|换地址|改收货|修改收货|收货地址改|新的收货地址)")

    def can_handle(self, context: dict) -> bool:
        if super().can_handle(context):
            return True
        user_input = (context.get("input") or "").lower()
        return bool(self._FALLBACK_RE.search(user_input))

    async def execute(self, context: dict) -> dict:
        slots = context.get("slots") or {}
        order_id = slots.get("orderId") or ""
        new_address = slots.get("newAddress") or ""

        if not order_id or not new_address:
            return {
                "success": False,
                "skillId": self.metadata["id"],
                "output": "修改地址需要提供订单编号和新的收货地址，请补充完整。",
                "error": "Missing required slots: orderId or newAddress",
            }

        spi_client = await self.get_spi_client(context.get("tenantId", "ecommerce"))
        order = await spi_client.get_order_detail(
            {
                "orderId": order_id,
                "userId": context.get("userId"),
                "threadId": context.get("threadId"),
                "tenantId": context.get("tenantId", "ecommerce"),
            }
        )
        if not order:
            return {
                "success": False,
                "skillId": self.metadata["id"],
                "output": f"未查询到订单号 [{order_id}] 的相关记录，请核对订单编号是否正确。",
                "error": f"Order {order_id} not found",
            }

        if order.get("isAddressModifiable") is False or str(order.get("status")) in ("SHIPPED", "DELIVERED", "CANCELLED"):
            return {
                "success": False,
                "skillId": self.metadata["id"],
                "output": (
                    f"抱歉，订单 [{order_id}] 当前状态为【{order.get('status')}】，包裹已发出或已完结，"
                    "系统无法直接拦截修改。如需更改建议联系派送员协商或拒收重新下单。"
                ),
            }

        # 🛡️ 高价值改址 HITL(2026-09-12 merchant 验收 07):技能快轨此前对
        # execute_order_action 直接传 is_approved=True,完全绕过步进引擎的审批
        # 门 —— ¥100 红线形同虚设。waiting 工单幂等认领(重复追问同话术),
        # 审批通过经 resume 重放落到工具路径确定性执行。
        try:
            order_total = float(order.get("totalAmount") or 0)
        except (TypeError, ValueError):
            order_total = 0.0
        if order_total > 100.0 and not (context.get("extra") or {}).get("isApproved"):
            from ..approvals.gatekeeper import ApprovalPolicyEngine

            ticket = await ApprovalPolicyEngine.create_pending_approval_ticket(
                {
                    "threadId": context.get("threadId") or "",
                    "userId": context.get("userId"),
                    "actionType": "changeShippingAddress",
                    "actionPayload": {"args": {"orderId": order_id, "newAddress": new_address}},
                    "jobId": None,
                    "stepToRun": {
                        "id": "skill_address_modification",
                        "description": f"Change shipping address for order {order_id}",
                    },
                    "currentPlan": {"subtasks": [{}]},
                    "currentIndex": 0,
                }
            )

            # 恢复计划随结果带回:run_agent 回合收口会用 result.task_plan 覆盖
            # TaskMemory —— 不随行则挂起计划被 bypass 空计划冲掉,审批通过后
            # resume 无计划可恢复(2026-09-12 实弹:approve 成功而地址未变)。
            awaiting_plan = {
                "goal": f"Change shipping address for order {order_id} (awaiting approval)",
                "subtasks": [
                    {
                        "id": "step_fast_change_address_skill",
                        "description": (
                            f"Call changeShippingAddress for order {order_id} "
                            f"with new address {new_address}"
                        ),
                        "status": "pending",
                        "result": {
                            "waitingForApproval": True,
                            "approvalId": ticket.get("approvalId"),
                        },
                    }
                ],
                "currentStepIndex": 0,
            }
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": (
                    f"订单 [{order_id}] 属于高价值订单（¥{order_total}），收货地址修改已提交人工审核"
                    f"（工单号 {ticket.get('approvalId')}）。审批通过后将自动执行变更，请稍候。"
                ),
                "nextAction": "finish",
                "taskPlan": awaiting_plan,
                "extra": {
                    "orderContext": {
                        "targetOrderId": order_id,
                        "orderStatus": order.get("status"),
                        "actionType": "modify_address",
                    }
                },
            }


            async def _persist_awaiting_plan() -> None:
                """挂起计划落库(与退款 HITL 同机制):审批通过经 resume 重放时
                HOT-RESUME 100% 复用本计划,executor 快路径确定性执行改址 —— 技能
                快轨没有 planner 计划,不落库则 resume 无计划可恢复,审批形同虚设
                (2026-09-12 实弹:approve 成功而地址未变)。"""
                from ..memory.task_memory import TaskMemory

                await TaskMemory(context.get("threadId") or "").save_task_state(
                    {
                        "goal": f"Change shipping address for order {order_id} (awaiting approval)",
                        "subtasks": [
                            {
                                "id": "step_fast_change_address_skill",
                                "description": (
                                    f"Call changeShippingAddress for order {order_id} "
                                    f"with new address {new_address}"
                                ),
                                "status": "pending",
                                "result": {
                                    "waitingForApproval": True,
                                    "approvalId": ticket.get("approvalId"),
                                },
                            }
                        ],
                        "currentStepIndex": 0,
                        "activeIntent": None,
                        "slots": {},
                        "orderContext": {"targetOrderId": order_id},
                    }
                )

            await _persist_awaiting_plan()
            return {
                "success": True,
                "skillId": self.metadata["id"],
                "output": (
                    f"订单 [{order_id}] 属于高价值订单（¥{order_total}），收货地址修改已提交人工审核"
                    f"（工单号 {ticket.get('approvalId')}）。审批通过后将自动执行变更，请稍候。"
                ),
                "nextAction": "finish",
                "extra": {
                    "orderContext": {
                        "targetOrderId": order_id,
                        "orderStatus": order.get("status"),
                        "actionType": "modify_address",
                    }
                },
            }

        async def _persist_awaiting_plan() -> None:
            """挂起计划落库(与退款 HITL 同机制):审批通过经 resume 重放时
            HOT-RESUME 100% 复用本计划,executor 快路径确定性执行改址 —— 技能
            快轨没有 planner 计划,不落库则 resume 无计划可恢复,审批形同虚设
            (2026-09-12 实弹:approve 成功而地址未变)。"""
            from ..memory.task_memory import TaskMemory

            await TaskMemory(context.get("threadId") or "").save_task_state(
                {
                    "goal": f"Change shipping address for order {order_id} (awaiting approval)",
                    "subtasks": [
                        {
                            "id": "step_fast_change_address_skill",
                            "description": (
                                f"Call changeShippingAddress for order {order_id} "
                                f"with new address {new_address}"
                            ),
                            "status": "pending",
                            "result": {
                                "waitingForApproval": True,
                                "approvalId": ticket.get("approvalId"),
                            },
                        }
                    ],
                    "currentStepIndex": 0,
                    "activeIntent": None,
                    "slots": {},
                    "orderContext": {"targetOrderId": order_id},
                }
            )

        action_result = await spi_client.execute_order_action(
            {
                "actionType": "MODIFY_ADDRESS",
                "orderId": order_id,
                "userId": context.get("userId"),
                "threadId": context.get("threadId"),
                "newAddress": new_address,
                "idempotencyKey": str(uuid.uuid4()),
                "tenantId": context.get("tenantId", "ecommerce"),
            }
        )
        if not action_result.get("success"):
            return {
                "success": False,
                "skillId": self.metadata["id"],
                "output": f"订单 [{order_id}] 修改地址失败: {action_result.get('message') or '系统繁忙，请稍后重试'}",
                "error": action_result.get("message"),
            }

        try:
            total_amount = float(order.get("totalAmount") or 0)
        except (TypeError, ValueError):
            total_amount = 0.0
        cards = [
            {
                "type": "order_card",
                "data": {
                    "orderId": order.get("orderId"),
                    "status": order.get("status"),
                    "totalAmount": total_amount,
                    "currency": "CNY",
                    "items": [
                        {
                            "title": i.get("title"),
                            "quantity": i.get("quantity"),
                            "price": float(i.get("price") or 0),
                            "imageUrl": i.get("imageUrl"),
                        }
                        for i in (order.get("items") or [])
                    ],
                },
            }
        ]
        return {
            "success": True,
            "skillId": self.metadata["id"],
            "output": f"已成功为您将订单 [{order_id}] 的收货地址变更为：{new_address}。包裹发出时将按照新地址配送。",
            "cards": cards,
            "nextAction": "finish",
            "extra": {
                "orderContext": {
                    "targetOrderId": order_id,
                    "orderStatus": order.get("status"),
                    "actionType": "modify_address",
                }
            },
        }
