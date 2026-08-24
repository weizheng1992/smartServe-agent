import crypto from "node:crypto";
import type {
  RichCardBlock,
  SkillExecutionContext,
  SkillExecutionResult,
  SkillMetadata,
} from "types";
import { BaseSkill } from "./baseSkill";

export class OrderAddressModificationSkill extends BaseSkill {
  public metadata: SkillMetadata = {
    id: "skill_order_address_modification",
    name: "极速改地址 SOP",
    description:
      "校验订单履约状态并执行地址变更，支持三级地址合规格式化与变更卡片渲染",
    category: "after_sale",
    triggerIntents: [
      "ORDER_MODIFY_ADDRESS",
      "modify_address",
      "order_modify_address",
    ],
    requiredTools: ["getOrderDetail", "executeOrderAction"],
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
    const newAddress = (context.slots?.newAddress as string) || "";

    if (!orderId || !newAddress) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: "修改地址需要提供订单编号和新的收货地址，请补充完整。",
        error: "Missing required slots: orderId or newAddress",
      };
    }

    const spiClient = await this.getSpiClient(context.tenantId);

    // Step 1: 查验订单履约状态
    const order = await spiClient.getOrderDetail({
      orderId,
      tenantId: context.tenantId,
    });

    if (!order) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: `未查询到订单号 [${orderId}] 的相关记录，请核对订单编号是否正确。`,
        error: `Order ${orderId} not found`,
      };
    }

    if (
      order.isAddressModifiable === false ||
      ["SHIPPED", "DELIVERED", "CANCELLED"].includes(order.status)
    ) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: `抱歉，订单 [${orderId}] 当前状态为【${order.status}】，包裹已发出或已完结，系统无法直接拦截修改。如需更改建议联系派送员协商或拒收重新下单。`,
      };
    }

    // Step 2: 派发执行修改
    const idempotencyKey = crypto.randomUUID();
    const actionResult = await spiClient.executeOrderAction({
      actionType: "MODIFY_ADDRESS",
      orderId,
      userId: context.userId,
      newAddress,
      idempotencyKey,
      tenantId: context.tenantId,
    });

    if (!actionResult.success) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: `订单 [${orderId}] 修改地址失败: ${actionResult.message || "系统繁忙，请稍后重试"}`,
        error: actionResult.message,
      };
    }

    const cards: RichCardBlock[] = [
      {
        type: "order_card",
        data: {
          orderId: order.orderId,
          status: order.status,
          totalAmount: Number(order.totalAmount),
          currency: "CNY",
          items: order.items.map((i) => ({
            title: i.title,
            quantity: i.quantity,
            price: Number(i.price),
            imageUrl: i.imageUrl,
          })),
        },
      },
    ];

    return {
      success: true,
      skillId: this.metadata.id,
      output: `已成功为您将订单 [${orderId}] 的收货地址变更为：${newAddress}。包裹发出时将按照新地址配送。`,
      cards,
      nextAction: "finish",
      extra: {
        orderContext: {
          targetOrderId: orderId,
          orderStatus: order.status,
          actionType: "modify_address",
        },
      },
    };
  }
}
