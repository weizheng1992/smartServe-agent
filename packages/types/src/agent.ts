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
