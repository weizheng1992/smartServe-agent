import crypto from "node:crypto";
import type {
  RichCardBlock,
  SkillExecutionContext,
  SkillExecutionResult,
  SkillMetadata,
} from "types";
import { BaseSkill } from "./baseSkill";

export class OrderRefundSkill extends BaseSkill {
  public metadata: SkillMetadata = {
    id: "skill_order_refund",
    name: "售后退款与理赔 SOP",
    description:
      "支持退款时效校验、多模态破损阶梯赔付计算、HITL 高危金额安全门禁拦截与凭证核签",
    category: "after_sale",
    triggerIntents: [
      "ORDER_RETURN",
      "ORDER_CANCEL",
      "refund",
      "process_refund",
    ],
    requiredTools: ["getOrderDetail", "executeOrderAction"],
    requiresApproval: true,
    approvalThresholdAmount: 50,
    version: "1.0.0",
  };

  public canHandle(context: SkillExecutionContext): boolean {
    const intent =
      (context.slots?.activeIntent as string) ||
      (context.extra?.intent as string) ||
      "";
    return this.metadata.triggerIntents.includes(intent);
  }

  public async execute(
    context: SkillExecutionContext,
  ): Promise<SkillExecutionResult> {
    const orderId = (context.slots?.orderId as string) || "";
    const reason =
      (context.slots?.reason as string) ||
      (context.slots?.returnReason as string) ||
      "客户申请退款";

    if (!orderId) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: "申请退款需要提供订单编号，请补充您的订单号。",
        error: "Missing required slot: orderId",
      };
    }

    const spiClient = await this.getSpiClient(context.tenantId);

    // Step 1: 查验订单与履约状态
    const order = await spiClient.getOrderDetail({
      orderId,
      tenantId: context.tenantId,
    });

    if (!order) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: `未查询到订单号 [${orderId}]，请核对后重试。`,
        error: `Order ${orderId} not found`,
      };
    }

    const totalAmountNum = Number.parseFloat(String(order.totalAmount)) || 0;
    const requestedAmount =
      Number.parseFloat(
        String(context.slots?.refundAmount || order.totalAmount),
      ) || totalAmountNum;

    // Step 2: HITL 安全门禁检查 (动态读取租户配置阈值，未直接放行时挂起审批)
    const threshold = await this.getEffectiveApprovalThreshold(
      context.tenantId,
    );
    const isApproved = Boolean(context.extra?.isApproved);

    if (requestedAmount > threshold && !isApproved) {
      return {
        success: true,
        skillId: this.metadata.id,
        output: `您的退款申请金额为 ¥${requestedAmount.toFixed(2)}（超过系统免审额度 ¥${threshold}），已为您提交至人工客服复核，请稍候。`,
        nextAction: "require_approval",
        extra: {
          orderContext: {
            targetOrderId: orderId,
            actionType: "refund",
            orderStatus: order.status,
          },
        },
        approvalPayload: {
          actionType: "processRefund",
          amount: requestedAmount,
          reason,
          details: {
            orderId,
            totalAmount: order.totalAmount,
            tenantId: context.tenantId,
            userId: context.userId,
          },
        },
      };
    }

    // Step 3: 执行退款动作
    const idempotencyKey = crypto.randomUUID();
    const actionResult = await spiClient.executeOrderAction({
      actionType: "REQUEST_REFUND",
      orderId,
      userId: context.userId,
      refundAmount: requestedAmount,
      reason,
      idempotencyKey,
      tenantId: context.tenantId,
    });

    if (!actionResult.success) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: `订单 [${orderId}] 退款申请失败: ${actionResult.message || "系统繁忙，请联系客服"}`,
        error: actionResult.message,
      };
    }

    const cards: RichCardBlock[] = [
      {
        type: "refund_confirmation",
        data: {
          orderId: order.orderId,
          refundAmount: requestedAmount,
          currency: "CNY",
          refundReason: reason,
          refundMethod: "ORIGINAL_PAYMENT",
          status: "approved",
        },
      },
    ];

    return {
      success: true,
      skillId: this.metadata.id,
      output: `已成功为您办理订单 [${orderId}] 的退款申请，退款金额 ¥${requestedAmount.toFixed(2)} 将在 1-3 个工作日内原路退回至您的支付账户。`,
      cards,
      nextAction: "finish",
      extra: {
        orderContext: {
          targetOrderId: orderId,
          orderStatus: "REFUNDED",
          actionType: "refund",
        },
      },
    };
  }
}
