import { Annotation } from '@langchain/langgraph';

export interface TaskPlan {
  goal: string;
  subtasks: {
    id: string;
    description: string;
    status: 'pending' | 'executing' | 'completed' | 'failed';
    result?: any;
  }[];
  currentStepIndex: number;
}

export interface IntentResult {
  intent: string;
  confidence: number;
}

export const AgentStateAnnotation = Annotation.Root({
  // Unique Thread & User metadata
  threadId: Annotation<string>(),
  userId: Annotation<string>(),
  jobId: Annotation<string>({
    reducer: (x, y) => y,
    default: () => '',
  }),

  // Current inputs and history
  input: Annotation<string>(),
  history: Annotation<any[]>({
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
      goal: '',
      subtasks: [],
      currentStepIndex: 0,
    }),
  }),

  // Memories loaded at start of loop
  shortMemory: Annotation<any[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  longMemoryFacts: Annotation<any[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  episodicEvents: Annotation<any[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  ragDocuments: Annotation<any[]>({
    reducer: (x, y) => y,
    default: () => [],
  }),
  businessConfig: Annotation<any>({
    reducer: (x, y) => ({ ...x, ...y }),
    default: () => ({
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
      refundAutoApprovalLimit: 100, // 默认超过 $100 的退款必须人工审核，低于 $100 的自动放行
    }),
  }),

  // Final formulation output
  output: Annotation<string>({
    reducer: (x, y) => y,
    default: () => '',
  }),

  // Loop control counters
  loopCount: Annotation<number>({
    reducer: (x, y) => y,
    default: () => 0,
  }),
});

/**
 * 🛡️ 统一对话历史清洗与拼装工具 (Unified History Cleaning & Assembly Utility)
 * 完美过滤任何因工具调用 (无 content)、数据传输异常 (null/undefined) 或底层 Mock 降级产生的不合规历史记录，
 * 彻底铲除 "Agent: undefined" / "Agent: null" 等隐形 Bug，确保大模型上下文 Prompt 绝对清爽。
 */
export function buildHistoryContext(shortMemory: any[]): string {
  if (!shortMemory || shortMemory.length === 0) return '';

  return shortMemory
    .map((m: any) => {
      if (!m) return '';
      const role = m.role === 'user' ? 'Customer' : m.role === 'system' ? 'System' : 'Agent';
      const content = m.content;
      if (
        content === undefined ||
        content === null ||
        String(content).trim() === '' ||
        String(content) === 'undefined' ||
        String(content) === 'null'
      ) {
        return '';
      }
      return `${role}: "${String(content).trim()}"`;
    })
    .filter((line: string) => line !== '')
    .join('\n');
}
