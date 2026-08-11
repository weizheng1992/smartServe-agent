import { Annotation } from "@langchain/langgraph";

export interface SubTaskResult {
  waitingForApproval?: boolean;
  approvalId?: string;
  actionType?: string;
  cancelledByUser?: boolean;
  expiredByTimeout?: boolean;
  rejectedByAdmin?: boolean;
  rejectionReason?: string;
  output?: unknown;
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

export interface IntentResult {
  intent: string;
  confidence: number;
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
    [key: string]: unknown;
  } | null;
  reason?: string;
  createdAt?: Date | string;
  updatedAt?: Date | string;
  [key: string]: unknown;
}

export const AgentStateAnnotation = Annotation.Root({
  // Unique Thread & User metadata
  threadId: Annotation<string>(),
  userId: Annotation<string>(),
  jobId: Annotation<string>({
    reducer: (x, y) => y,
    default: () => "",
  }),

  // Current inputs and history
  input: Annotation<string>(),
  inputEmbedding: Annotation<number[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  history: Annotation<ChatMessage[]>({
    reducer: (x, y) => x.concat(y),
    default: () => [],
  }),

  // Intent classification
  intents: Annotation<IntentResult[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),

  // Task Memory
  taskPlan: Annotation<TaskPlan>({
    reducer: (x, y) => ({ ...x, ...y }),
    default: () => ({
      goal: "",
      subtasks: [],
      currentStepIndex: 0,
    }),
  }),

  // Memories loaded at start of loop
  shortMemory: Annotation<ChatMessage[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  longMemoryFacts: Annotation<unknown[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  episodicEvents: Annotation<unknown[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  ragDocuments: Annotation<RagDocument[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  businessConfig: Annotation<BusinessConfig>({
    reducer: (x, y) => ({ ...x, ...y }),
    default: () => ({
      businessId: "ecommerce",
      systemPrompt:
        "You are an advanced, professional AI Customer Support Agent specialized in E-Commerce. Help users resolve order, shipping, and refund queries.",
      intents: {
        order_status: { description: "Track or check order delivery status." },
        refund: { description: "Process or request refunds." },
        general_query: { description: "General customer questions." },
      },
      tools: ["getOrderStatus", "processRefund", "listUserOrders"],
      executionMode: "plan-and-execute",
      confidenceThresholds: { high: 0.85, mid: 0.6 },
      refundAutoApprovalLimit: 100, // 默认超过 $100 的退还必须人工审核，低于 $100 的自动放行
    }),
  }),

  // Final formulation output
  output: Annotation<string>({
    reducer: (x, y) => y,
    default: () => "",
  }),

  // Loop control counters
  loopCount: Annotation<number>({
    reducer: (x, y) => y,
    default: () => 0,
  }),

  // 🛡️ [图级别硬熔断控制属性]: 累计节点转移总次数与执行错误累计，防范算力自旋
  globalTransitionsCount: Annotation<number>({
    reducer: (x, y) => (y === -1 ? 0 : x + y),
    default: () => 0,
  }),
  toolErrorsCount: Annotation<number>({
    reducer: (x, y) => (y === -1 ? 0 : x + y),
    default: () => 0,
  }),
});

/**
 * 🛡️ 统一对话历史清洗与拼装工具 (Unified History Cleaning & Assembly Utility)
 * 完美过滤任何因工具调用 (无 content)、数据传输异常 (null/undefined) 或底层 Mock 降级产生的不合规历史记录，
 * 彻底铲除 "Agent: undefined" / "Agent: null" 等隐形 Bug，确保大模型上下文 Prompt 绝对清爽。
 */
export function buildHistoryContext(shortMemory: ChatMessage[]): string {
  if (!shortMemory || shortMemory.length === 0) return "";

  return shortMemory
    .map((m: ChatMessage) => {
      if (!m) return "";
      const role =
        m.role === "user"
          ? "Customer"
          : m.role === "system"
            ? "System"
            : "Agent";
      const content = m.content;
      if (
        content === undefined ||
        content === null ||
        String(content).trim() === "" ||
        String(content) === "undefined" ||
        String(content) === "null"
      ) {
        return "";
      }
      return `${role}: "${String(content).trim()}"`;
    })
    .filter((line: string) => line !== "")
    .join("\n");
}
