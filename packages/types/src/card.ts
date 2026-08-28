export type RichCardType =
  | 'order_card'
  | 'order_picker'
  | 'tracking_timeline'
  | 'refund_confirmation'
  | 'quick_replies'
  | 'damage_assessment'
  | 'product_ranking'
  | 'cart_card'
  | 'step_progress'
  | 'interactive_product';

export type CardHydrationState = 'skeleton' | 'hydrating' | 'ready' | 'action_pending' | 'settled';

export interface StepProgressItem {
  stepIndex: number;
  title: string;
  description?: string;
  status: 'upcoming' | 'current' | 'completed' | 'error';
  actionRequired?: {
    actionType: 'input_text' | 'select_option' | 'upload_evidence' | 'confirm_button';
    placeholder?: string;
    options?: Array<{ label: string; value: string }>;
    submitAction: string;
    buttonLabel?: string;
  };
}

export interface StepProgressCardData {
  ticketId?: string;
  orderId?: string;
  title: string;
  currentStep: number;
  totalSteps: number;
  steps: StepProgressItem[];
  metadata?: Record<string, unknown>;
  settledSummary?: string;
}

export interface ProductSkuSpec {
  skuId: string;
  title: string;
  color?: string;
  size?: string;
  price: number;
  stock: number;
  imageUrl?: string;
}

export interface InteractiveProductCardData {
  productId: string;
  title: string;
  subtitle?: string;
  imageUrl?: string;
  basePrice: number;
  skus: ProductSkuSpec[];
  selectedSkuId?: string;
  selectedQuantity?: number;
  actions?: Array<{
    label: string;
    action: string;
    payload?: Record<string, unknown>;
  }>;
}

export interface CartItemData {
  id?: string;
  skuId?: string;
  skuCode?: string;
  spuId?: string;
  title: string;
  skuTitle?: string;
  price: number;
  quantity: number;
  imageUrl?: string;
  specSummary?: string;
}

export interface CartCardData {
  actionType: 'added' | 'view' | 'updated' | 'cleared' | 'checkout';
  title: string;
  items: CartItemData[];
  totalQuantity: number;
  totalAmount: number;
  currency?: string;
  actions?: Array<{
    label: string;
    action: string;
    payload?: Record<string, unknown>;
  }>;
}

export interface RankedProductItem {
  rank: number;
  productId: string;
  name: string;
  category: string;
  price: number;
  costPrice?: number;
  stock?: number;
  totalVolume: number;
  totalGmv: number;
  grossProfit: number;
  marginRate: string;
  metricScore: number;
  metricDisplay: string;
}

export interface ProductRankingCardData {
  rankingMetric: string;
  metricLabel: string;
  metricUnit: string;
  itemCount: number;
  summary?: string;
  products: RankedProductItem[];
}

export interface OrderItem {
  id?: string;
  title: string;
  price: number;
  quantity: number;
  imageUrl?: string;
}

export interface OrderCardData {
  orderId: string;
  status: string;
  totalAmount: number;
  currency?: string;
  items?: OrderItem[];
  carrier?: string;
  trackingNumber?: string;
  createdAt?: string;
  actions?: Array<{
    label: string;
    action: string;
    payload?: Record<string, unknown>;
  }>;
}

export interface TrackingTimelineEvent {
  time: string;
  location?: string;
  description: string;
  status?: 'completed' | 'in_transit' | 'pending' | 'delivered';
}

export interface TrackingTimelineData {
  trackingNumber: string;
  carrier: string;
  currentStatus: string;
  estimatedDelivery?: string;
  timeline: TrackingTimelineEvent[];
}

export interface RefundConfirmationData {
  orderId: string;
  refundAmount: number;
  currency?: string;
  refundReason: string;
  refundMethod: string;
  status: 'pending_confirmation' | 'submitted' | 'approved' | 'rejected';
  requiresApproval?: boolean;
}

export interface QuickReplyOption {
  label: string;
  action: string;
  payload?: Record<string, unknown>;
  icon?: string;
}

export interface QuickRepliesData {
  title?: string;
  options: QuickReplyOption[];
}

export interface DamageAssessmentData {
  damageLevel: 'negligible' | 'minor' | 'severe';
  summary: string;
  confidence: number;
  suggestedAction: 'auto_refund' | 'require_inspection' | 'human_review';
  imageUrl?: string;
}

export interface OrderPickerCardData {
  title?: string;
  totalCount: number;
  orders: OrderCardData[];
}

export type RichCardBlock = {
  id?: string;
  hydrationState?: CardHydrationState;
} & (
  | { type: 'order_card'; data: OrderCardData }
  | { type: 'order_picker'; data: OrderPickerCardData }
  | { type: 'tracking_timeline'; data: TrackingTimelineData }
  | { type: 'refund_confirmation'; data: RefundConfirmationData }
  | { type: 'quick_replies'; data: QuickRepliesData }
  | { type: 'damage_assessment'; data: DamageAssessmentData }
  | { type: 'product_ranking'; data: ProductRankingCardData }
  | { type: 'cart_card'; data: CartCardData }
  | { type: 'step_progress'; data: StepProgressCardData }
  | { type: 'interactive_product'; data: InteractiveProductCardData }
);

export interface MultimodalMessagePayload {
  message: string;
  imageUrls?: string[];
  cards?: RichCardBlock[];
}
