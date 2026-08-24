import { Annotation } from "@langchain/langgraph";
import type {
  AgentDomainRole,
  BusinessConfig,
  CartContext,
  ChatMessage,
  DamageAssessmentData,
  IntentResult,
  OrderContext,
  PendingApprovalRecord,
  RagDocument,
  RichCardBlock,
  ShoppingGuideContext,
  SubTask,
  SubTaskResult,
  TaskPlan,
} from "types";

export type {
  AgentDomainRole,
  BusinessConfig,
  CartContext,
  ChatMessage,
  DamageAssessmentData,
  IntentResult,
  OrderContext,
  PendingApprovalRecord,
  RagDocument,
  RichCardBlock,
  ShoppingGuideContext,
  SubTask,
  SubTaskResult,
  TaskPlan,
};

export type AgentState = typeof AgentStateAnnotation.State;

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
  imageUrls: Annotation<string[]>({
    reducer: (x, y) => (y !== undefined ? y : x),
    default: () => [],
  }),
  damageAssessment: Annotation<DamageAssessmentData | undefined>({
    reducer: (x, y) => (y !== undefined ? y : x),
    default: () => undefined,
  }),
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

  // 🎯 Multi-Agent 专属角色与领域上下文总线
  activeDomainRole: Annotation<AgentDomainRole | undefined>({
    reducer: (x, y) => (y !== undefined ? y : x),
    default: () => undefined,
  }),
  guideContext: Annotation<ShoppingGuideContext | undefined>({
    reducer: (x, y) => (y !== undefined ? { ...x, ...y } : x),
    default: () => undefined,
  }),
  cartContext: Annotation<CartContext | undefined>({
    reducer: (x, y) => (y !== undefined ? { ...x, ...y } : x),
    default: () => undefined,
  }),
  orderContext: Annotation<OrderContext | undefined>({
    reducer: (x, y) => (y !== undefined ? { ...x, ...y } : x),
    default: () => undefined,
  }),

  // Structured Rich Cards Output
  cards: Annotation<RichCardBlock[]>({
    reducer: (x, y) => (y !== undefined ? y : x),
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
