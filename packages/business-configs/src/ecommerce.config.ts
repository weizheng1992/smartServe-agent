export interface BusinessConfig {
  businessId: string;
  systemPrompt: string;
  intents: Record<string, { description: string }>;
  tools: string[];
  executionMode: 'react' | 'plan-and-execute';
  confidenceThresholds: { high: number; mid: number };
}

export const ecommerceConfig: BusinessConfig = {
  businessId: 'ecommerce',
  systemPrompt:
    'You are an advanced, professional AI Customer Support Agent specialized in E-Commerce. Help users resolve order, shipping, and refund queries.',
  intents: {
    order_status: { description: 'Track or check order delivery status.' },
    refund: { description: 'Process or request refunds.' },
    general_query: { description: 'General customer questions.' },
  },
  tools: ['getOrderStatus', 'processRefund'],
  executionMode: 'plan-and-execute',
  confidenceThresholds: { high: 0.85, mid: 0.6 },
};
