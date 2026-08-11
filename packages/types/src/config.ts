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
