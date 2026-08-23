export interface ConversationRecord {
  threadId: string;
  userId: string;
  businessId: string;
  channel: string;
  status: "active" | "waiting_approval" | "resolved";
  intent: string;
  messageCount: number;
  totalTokens: number;
  costUsd: number;
  lastMessage: string;
  updatedAt: string;
}
