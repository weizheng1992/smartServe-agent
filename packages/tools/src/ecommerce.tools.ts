import { z } from 'zod';
import { redis, toolCache, useRedis } from './cache';
import { MallDomainService } from './mallDomainService';
import { OrderDomainService } from './orderDomainService';
import { registerTool } from './registry';

export { redis, useRedis, toolCache, MallDomainService };

export const getOrderStatus = {
  name: 'getOrderStatus',
  description:
    'Get the status of a specific order by order ID. Secured: Only allowed if the order belongs to the currently logged-in customer.',
  schema: z.object({
    orderId: z.string().describe('The unique order identifier.'),
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
  name: 'processRefund',
  description:
    'Process a refund for an order. Secured: Only allowed if the order belongs to the currently logged-in customer.',
  schema: z.object({
    orderId: z.string().describe('The unique order identifier.'),
    reason: z.string().describe('The reason for processing the refund.'),
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
  name: 'listUserOrders',
  description: 'List all recent orders and tracking status for the current customer.',
  schema: z.object({}),
  execute: async ({ threadId }: { threadId?: string }) => {
    return OrderDomainService.listUserOrders(threadId);
  },
};

export const changeShippingAddress = {
  name: 'changeShippingAddress',
  description:
    'Modify the shipping address of an order before it gets shipped. Secured: Only allowed if the order belongs to the currently logged-in customer.',
  schema: z.object({
    orderId: z.string().describe('The unique order identifier.'),
    newAddress: z.string().describe('The new physical shipping address.'),
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
    return OrderDomainService.changeShippingAddress(orderId, newAddress, threadId, isApproved);
  },
};

export const generateInvoice = {
  name: 'generateInvoice',
  description:
    'Generate a structured electronic tax invoice for a completed order. Secured: Only allowed if the order belongs to the currently logged-in customer.',
  schema: z.object({
    orderId: z.string().describe('The unique order identifier.'),
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
  name: 'recordUserPreference',
  description:
    'Record specific consumer preferences of the current customer (such as clothing size, favorite color, stylistic preference, material allergies/restrictions) into long-term memories for future search and sizing recommendation.',
  schema: z.object({
    preferenceType: z
      .enum(['size', 'color', 'brand', 'style', 'material', 'other'])
      .describe('偏好类型，如 size 代表尺寸，color 代表颜色，material 代表过敏或避雷材质等'),
    preferenceValue: z
      .string()
      .describe('具体的偏好数值或文字表达，例如 "鞋码42.5/上衣L码"、"喜欢纯白"、"对羊毛过敏，刺痒"'),
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
    return OrderDomainService.recordUserPreference(preferenceType, preferenceValue, threadId);
  },
};

export const createOrder = {
  name: 'createOrder',
  description: 'Create a new customer order. Automatically resolves user context and tenant ID.',
  schema: z.object({
    userId: z
      .string()
      .optional()
      .describe('The user ID to associate the order with. If omitted, resolved from session thread context.'),
    orderId: z.string().optional().describe('Optional custom order ID.'),
    businessId: z.string().optional().describe('Optional merchant business ID.'),
    totalAmount: z.number().optional().describe('Total amount of the order.'),
    carrier: z.string().optional().describe('Shipping carrier name.'),
    items: z
      .array(
        z.object({
          productId: z.string().describe('The product unique ID.'),
          quantity: z.number().describe('Quantity of the product.'),
          priceAtPurchase: z.number().optional().describe('Purchase unit price.'),
        }),
      )
      .optional()
      .describe('List of order items included in this order.'),
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
      const ctx = await OrderDomainService.getThreadSessionContext(args.threadId);
      if (!effectiveUserId && ctx.userId) effectiveUserId = ctx.userId;
      if (!effectiveBusinessId && ctx.businessId) effectiveBusinessId = ctx.businessId;
    }
    return OrderDomainService.createOrder({
      ...args,
      userId: effectiveUserId || '',
      businessId: effectiveBusinessId || 'ecommerce',
    });
  },
};

export const queryProductRanking = {
  name: 'queryProductRanking',
  description:
    'Query and rank mall products across multi-dimensional metrics (GMV sales revenue, shipment volume, gross profit, margin rate, or stock risk) with tenant isolation and manager ownership security.',
  schema: z.object({
    rankingMetric: z
      .string()
      .optional()
      .describe(
        "Ranking metric identifier: 'gmv' (total sales revenue), 'volume' (sales count), 'gross_profit' (net gross profit), 'margin_rate' (profit margin %), 'stock_risk' (stagnant inventory). Default is 'gmv'.",
      ),
    managerOnly: z
      .boolean()
      .optional()
      .describe(
        "Whether to filter products specifically managed by the current user ('我负责的商品'). Defaults to true.",
      ),
    category: z
      .string()
      .optional()
      .describe("Optional product category filter (e.g. 'shoes', 'apparel', 'accessories')."),
    limit: z.number().optional().describe('Maximum number of ranked products to return. Defaults to 5.'),
  }),
  execute: async (args: {
    rankingMetric?: string;
    managerOnly?: boolean;
    category?: string;
    limit?: number;
    threadId?: string;
  }) => {
    return OrderDomainService.queryProductRanking(args);
  },
};

export const getUserAddresses = {
  name: 'getUserAddresses',
  description: 'Get all saved recipient delivery addresses for the current user, including tags and default flags.',
  schema: z.object({
    userId: z.string().optional().describe('User identifier. Resolved automatically from context if omitted.'),
  }),
  execute: async (args: { userId?: string; threadId?: string }) => {
    return MallDomainService.getUserAddresses(args.userId, undefined, args.threadId);
  },
};

export const saveUserAddress = {
  name: 'saveUserAddress',
  description: 'Save or create a new delivery address for the current customer.',
  schema: z.object({
    receiverName: z.string().describe('Recipient name.'),
    receiverPhone: z.string().describe('Recipient phone number.'),
    province: z.string().describe('Province or state.'),
    city: z.string().describe('City name.'),
    district: z.string().describe('District or county.'),
    detailAddress: z.string().describe('Street address and door number.'),
    tag: z.enum(['home', 'company', 'school', 'other']).optional().describe('Address category tag.'),
    isDefault: z.boolean().optional().describe('Whether to set this address as default.'),
  }),
  execute: async (args: {
    receiverName: string;
    receiverPhone: string;
    province: string;
    city: string;
    district: string;
    detailAddress: string;
    tag?: 'home' | 'company' | 'school' | 'other';
    isDefault?: boolean;
    threadId?: string;
  }) => {
    return MallDomainService.saveUserAddress(args);
  },
};

export const queryProductSkus = {
  name: 'queryProductSkus',
  description:
    'Query detailed product SKU specifications (color, size, edition) along with real-time stock and prices.',
  schema: z.object({
    productId: z.string().optional().describe('Product unique identifier.'),
    color: z.string().optional().describe("Color name filter (e.g. '极夜黑', '白')."),
    size: z.string().optional().describe("Shoe or apparel size filter (e.g. '42', '42.5', 'L')."),
    inStockOnly: z.boolean().optional().describe('Filter only SKUs that are currently in stock.'),
  }),
  execute: async (args: {
    productId?: string;
    color?: string;
    size?: string;
    inStockOnly?: boolean;
    threadId?: string;
  }) => {
    return MallDomainService.queryProductSkus(args);
  },
};

export const queryPackageTracking = {
  name: 'queryPackageTracking',
  description: 'Query real-time parcel delivery tracking status, courier details, and chronological timeline nodes.',
  schema: z.object({
    orderId: z.string().optional().describe('Order ID to look up package tracking.'),
    trackingNumber: z.string().optional().describe('Specific express tracking number (SF, JD, ZTO, etc.).'),
  }),
  execute: async (args: {
    orderId?: string;
    trackingNumber?: string;
    threadId?: string;
  }) => {
    return MallDomainService.queryPackageTracking(args);
  },
};

export const queryProductReviews = {
  name: 'queryProductReviews',
  description: 'Query customer feedback, ratings, sentiment summary, and sizing/fit consensus for a product.',
  schema: z.object({
    productId: z.string().optional().describe('Product ID to inspect reviews for.'),
    fitFeedback: z
      .enum(['true_to_size', 'runs_small', 'runs_large'])
      .optional()
      .describe('Filter reviews by specific fit feedback.'),
    sentiment: z.enum(['positive', 'neutral', 'negative']).optional().describe('Sentiment filter.'),
    limit: z.number().optional().describe('Maximum number of reviews to return.'),
  }),
  execute: async (args: {
    productId?: string;
    fitFeedback?: 'true_to_size' | 'runs_small' | 'runs_large';
    sentiment?: 'positive' | 'neutral' | 'negative';
    limit?: number;
    threadId?: string;
  }) => {
    return MallDomainService.queryProductReviews(args);
  },
};

export const applyAfterSale = {
  name: 'applyAfterSale',
  description: 'Submit an after-sale customer service ticket (refund only, return and refund, or exchange).',
  schema: z.object({
    orderId: z.string().describe('The order ID to apply after-sale for.'),
    type: z.enum(['refund_only', 'return_and_refund', 'exchange']).describe('After-sale type.'),
    reason: z
      .enum(['wrong_size', 'quality_issue', 'not_as_described', 'no_reason_7d'])
      .describe('Structured return/refund reason code.'),
    reasonDescription: z.string().optional().describe('Optional text explanation of the issue.'),
    refundAmount: z.number().optional().describe('Requested refund amount.'),
  }),
  execute: async (args: {
    orderId: string;
    type: 'refund_only' | 'return_and_refund' | 'exchange';
    reason: 'wrong_size' | 'quality_issue' | 'not_as_described' | 'no_reason_7d';
    reasonDescription?: string;
    refundAmount?: number;
    threadId?: string;
  }) => {
    return MallDomainService.applyAfterSale(args);
  },
};

registerTool(getOrderStatus);
registerTool(processRefund);
registerTool(listUserOrders);
registerTool(changeShippingAddress);
registerTool(generateInvoice);
registerTool(recordUserPreference);
registerTool(createOrder);
registerTool(queryProductRanking);
registerTool(getUserAddresses);
registerTool(saveUserAddress);
registerTool(queryProductSkus);
registerTool(queryPackageTracking);
registerTool(queryProductReviews);
registerTool(applyAfterSale);
