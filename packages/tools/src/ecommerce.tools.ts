import { z } from "zod";
import { redis, toolCache, useRedis } from "./cache";
import { OrderDomainService } from "./orderDomainService";
import { registerTool } from "./registry";

export { redis, useRedis, toolCache };

export const getOrderStatus = {
  name: "getOrderStatus",
  description:
    "Get the status of a specific order by order ID. Secured: Only allowed if the order belongs to the currently logged-in customer.",
  schema: z.object({
    orderId: z.string().describe("The unique order identifier."),
  }),
  execute: async ({
    orderId,
    threadId,
  }: {
    orderId: string;
    threadId?: string;
  }) => {
    return OrderDomainService.getOrderStatus(orderId, threadId);
  },
};

export const processRefund = {
  name: "processRefund",
  description:
    "Process a refund for an order. Secured: Only allowed if the order belongs to the currently logged-in customer.",
  schema: z.object({
    orderId: z.string().describe("The unique order identifier."),
    reason: z.string().describe("The reason for processing the refund."),
  }),
  execute: async ({
    orderId,
    reason,
    threadId,
    amount,
  }: {
    orderId: string;
    reason: string;
    threadId?: string;
    amount?: string;
  }) => {
    return OrderDomainService.processRefund(orderId, reason, threadId, amount);
  },
};

export const listUserOrders = {
  name: "listUserOrders",
  description:
    "List all recent orders and tracking status for the current customer.",
  schema: z.object({}),
  execute: async ({ threadId }: { threadId?: string }) => {
    return OrderDomainService.listUserOrders(threadId);
  },
};

export const changeShippingAddress = {
  name: "changeShippingAddress",
  description:
    "Modify the shipping address of an order before it gets shipped. Secured: Only allowed if the order belongs to the currently logged-in customer.",
  schema: z.object({
    orderId: z.string().describe("The unique order identifier."),
    newAddress: z.string().describe("The new physical shipping address."),
  }),
  execute: async ({
    orderId,
    newAddress,
    threadId,
    isApproved,
  }: {
    orderId: string;
    newAddress: string;
    threadId?: string;
    isApproved?: boolean;
  }) => {
    return OrderDomainService.changeShippingAddress(
      orderId,
      newAddress,
      threadId,
      isApproved,
    );
  },
};

export const generateInvoice = {
  name: "generateInvoice",
  description:
    "Generate a structured electronic tax invoice for a completed order. Secured: Only allowed if the order belongs to the currently logged-in customer.",
  schema: z.object({
    orderId: z.string().describe("The unique order identifier."),
  }),
  execute: async ({
    orderId,
    threadId,
  }: {
    orderId: string;
    threadId?: string;
  }) => {
    return OrderDomainService.generateInvoice(orderId, threadId);
  },
};

export const recordUserPreference = {
  name: "recordUserPreference",
  description:
    "Record specific consumer preferences of the current customer (such as clothing size, favorite color, stylistic preference, material allergies/restrictions) into long-term memories for future search and sizing recommendation.",
  schema: z.object({
    preferenceType: z
      .enum(["size", "color", "brand", "style", "material", "other"])
      .describe(
        "偏好类型，如 size 代表尺寸，color 代表颜色，material 代表过敏或避雷材质等",
      ),
    preferenceValue: z
      .string()
      .describe(
        '具体的偏好数值或文字表达，例如 "鞋码42.5/上衣L码"、"喜欢纯白"、"对羊毛过敏，刺痒"',
      ),
  }),
  execute: async ({
    preferenceType,
    preferenceValue,
    threadId,
  }: {
    preferenceType: string;
    preferenceValue: string;
    threadId?: string;
  }) => {
    return OrderDomainService.recordUserPreference(
      preferenceType,
      preferenceValue,
      threadId,
    );
  },
};

export const createOrder = {
  name: "createOrder",
  description:
    "Create a new customer order. Automatically resolves user context and tenant ID.",
  schema: z.object({
    userId: z
      .string()
      .optional()
      .describe(
        "The user ID to associate the order with. If omitted, resolved from session thread context.",
      ),
    orderId: z.string().optional().describe("Optional custom order ID."),
    businessId: z
      .string()
      .optional()
      .describe("Optional merchant business ID."),
    totalAmount: z.number().optional().describe("Total amount of the order."),
    carrier: z.string().optional().describe("Shipping carrier name."),
    items: z
      .array(
        z.object({
          productId: z.string().describe("The product unique ID."),
          quantity: z.number().describe("Quantity of the product."),
          priceAtPurchase: z
            .number()
            .optional()
            .describe("Purchase unit price."),
        }),
      )
      .optional()
      .describe("List of order items included in this order."),
  }),
  execute: async (args: {
    userId?: string;
    orderId?: string;
    businessId?: string;
    totalAmount?: number;
    carrier?: string;
    items?: Array<{
      productId: string;
      quantity: number;
      priceAtPurchase?: number;
    }>;
    threadId?: string;
  }) => {
    let effectiveUserId = args.userId;
    let effectiveBusinessId = args.businessId;
    if ((!effectiveUserId || !effectiveBusinessId) && args.threadId) {
      const ctx = await OrderDomainService.getThreadSessionContext(
        args.threadId,
      );
      if (!effectiveUserId && ctx.userId) effectiveUserId = ctx.userId;
      if (!effectiveBusinessId && ctx.businessId)
        effectiveBusinessId = ctx.businessId;
    }
    return OrderDomainService.createOrder({
      ...args,
      userId: effectiveUserId || "",
      businessId: effectiveBusinessId || "ecommerce",
    });
  },
};

registerTool(getOrderStatus);
registerTool(processRefund);
registerTool(listUserOrders);
registerTool(changeShippingAddress);
registerTool(generateInvoice);
registerTool(recordUserPreference);
registerTool(createOrder);
