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
  | 'shopping_guide'
  | 'cart_manage'
  | 'faq'
  | 'chat';

// 一级意图标准枚举
export enum AgentIntentType {
  METRIC_QUERY = 'metric_query', // 指标查询（走 metric registry）
  ORDER_QUERY = 'order_status', // 查询订单、物流
  ORDER_RETURN = 'refund', // 申请退款/退货
  ORDER_MODIFY_ADDRESS = 'order_modify_address', // 修改收货地址
  ORDER_CANCEL = 'order_cancel', // 取消订单
  SHOPPING_GUIDE = 'shopping_guide', // 商品导购/多轮选品
  CART_MANAGE = 'cart_manage', // 购物车/加购/改规格
  FAQ = 'faq',
  CHAT = 'chat',
  HUMAN_ESCALATION = 'human_escalation',
}

// 🎯 专职 Agent 领域角色定义 (Domain-specific Agent Roles)
export type AgentDomainRole = 'router' | 'shopping_guide' | 'cart' | 'order_service' | 'chitchat';

// 🛍️ 导购专有上下文 (Shopping Guide Context)
export interface ShoppingGuideContext {
  candidateProductIds?: string[]; // 当前向用户推荐的候选商品 ID 列表（用于下文指代消解）
  extractedPreferences?: Record<string, string>; // 已探明的用户画像偏好（如风格、预算、尺码、颜色）
  activeCategory?: string; // 当前关注的类目
  clarificationRound?: number; // 已进行的探问澄清轮数
  lastSearchQuery?: string;
}

// 🛒 购物车专有上下文 (Cart Context)
export interface CartContext {
  lastModifiedItemId?: string;
  items?: Array<{
    skuId: string;
    quantity: number;
    title?: string;
    price?: number;
    spec?: string;
  }>;
  totalAmount?: number;
}

// 📦 订单/售后专有上下文 (Order & Care Context)
export interface OrderContext {
  targetOrderId?: string;
  pendingApprovalId?: string;
  orderStatus?: string;
  actionType?: 'status_query' | 'modify_address' | 'refund' | 'cancel';
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
