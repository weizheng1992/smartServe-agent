export function getMerchantDisplayName(businessId?: string): string {
  const clean = (businessId || "ecommerce").toLowerCase();
  if (clean === "adidas") return "Adidas 官方旗舰店";
  if (clean === "nike") return "Nike 官方旗舰店";
  if (clean === "ecommerce") return "官方综合商城";
  return `${clean.charAt(0).toUpperCase() + clean.slice(1)} 官方商城`;
}

export interface RagDocument {
  chunkText: string;
  contextualSummary?: string;
  score?: number;
  [key: string]: unknown;
}

export interface BusinessConfig {
  businessId: string;
  systemPrompt?: string;
  intents?: Record<string, { description: string }>;
  tools?: string[];
  executionMode?: string;
  confidenceThresholds?: { high: number; mid: number };
  refundAutoApprovalLimit?: number;
  [key: string]: unknown;
}
