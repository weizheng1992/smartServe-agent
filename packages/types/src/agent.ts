export type SupportedIntent =
  | 'order_status'
  | 'refund'
  | 'out_of_scope'
  | 'general_query'
  | 'human_escalation'
  | 'order_modify_address'
  | 'order_query'
  | 'order_return'
  | 'order_cancel'
  | 'metric_query'
  | 'faq'
  | 'chat';

// 一级意图标准枚举
export enum AgentIntentType {
  METRIC_QUERY = 'metric_query', // 指标查询（走 metric registry）
  ORDER_QUERY = 'order_status', // 查询订单、物流
  ORDER_RETURN = 'refund', // 申请退款/退货
  ORDER_MODIFY_ADDRESS = 'order_modify_address', // 修改收货地址
  ORDER_CANCEL = 'order_cancel', // 取消订单
  FAQ = 'faq',
  CHAT = 'chat',
  HUMAN_ESCALATION = 'human_escalation',
}

// 槽位：每个订单类意图必须抽取的参数
export interface OrderTaskSlots {
  orderId?: string; // 订单号（核心必填）
  newAddress?: string; // 修改地址时需要
  returnReason?: string; // 退货原因
  productId?: string;
  metricKey?: string;
  [key: string]: unknown;
}

// Agent 输出结构化对象
export interface AgentTaskSpec {
  intentType: AgentIntentType | string;
  slots: OrderTaskSlots;
  confidence: number;
  missingSlots: string[]; // 缺失哪些必填参数，用来多轮追问
  clarificationMessage?: string;
}

export interface IntentResult {
  intent: string;
  confidence: number;
  type?: 'primary' | 'secondary';
  entities?: Record<string, string>;
  taskSpec?: AgentTaskSpec;
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
  status: 'pending' | 'executing' | 'completed' | 'failed';
  result?: SubTaskResult;
}

export interface TaskPlan {
  goal: string;
  subtasks: SubTask[];
  currentStepIndex: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | string;
  content?: string | null;
  [key: string]: unknown;
}
