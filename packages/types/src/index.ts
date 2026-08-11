export type SupportedIntent =
  | "order_status"
  | "refund"
  | "out_of_scope"
  | "general_query"
  | "human_escalation";

export interface IntentResult {
  intent: string;
  confidence: number;
}

export interface SubTaskResult {
  waitingForApproval?: boolean;
  approvalId?: string;
  actionType?: string;
  cancelledByUser?: boolean;
  expiredByTimeout?: boolean;
  rejectedByAdmin?: boolean;
  rejectionReason?: string;
  output?: unknown;
  toolExecuted?: string;
  message?: string;
  [key: string]: unknown;
}

export interface SubTask {
  id: string;
  description: string;
  status: "pending" | "executing" | "completed" | "failed";
  result?: SubTaskResult;
}

export interface TaskPlan {
  goal: string;
  subtasks: SubTask[];
  currentStepIndex: number;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system" | string;
  content?: string | null;
  [key: string]: unknown;
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

export interface PendingApprovalRecord {
  id: string;
  threadId: string;
  status:
    "pending" | "approved" | "rejected" | "cancelled" | "expired" | string;
  actionType?: string;
  actionPayload?: {
    orderId?: string;
    refundAmount?: number;
    rejectionReason?: string;
    args?: Record<string, unknown>;
    [key: string]: unknown;
  } | null;
  reason?: string;
  createdAt?: Date | string;
  updatedAt?: Date | string;
  [key: string]: unknown;
}

export interface IntentLog {
  id?: string;
  threadId: string;
  inputText: string;
  predictedIntents: IntentResult[];
  method: "rule" | "embedding" | "llm" | "semantic_cache" | string;
  confidence: number;
  createdAt?: Date | string;
}
