export type RichCardType =
  | "order_card"
  | "tracking_timeline"
  | "refund_confirmation"
  | "quick_replies"
  | "damage_assessment";

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
  status?: "completed" | "in_transit" | "pending" | "delivered";
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
  status: "pending_confirmation" | "submitted" | "approved" | "rejected";
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
  damageLevel: "negligible" | "minor" | "severe";
  summary: string;
  confidence: number;
  suggestedAction: "auto_refund" | "require_inspection" | "human_review";
  imageUrl?: string;
}

export type RichCardBlock =
  | { type: "order_card"; data: OrderCardData }
  | { type: "tracking_timeline"; data: TrackingTimelineData }
  | { type: "refund_confirmation"; data: RefundConfirmationData }
  | { type: "quick_replies"; data: QuickRepliesData }
  | { type: "damage_assessment"; data: DamageAssessmentData };

export interface MultimodalMessagePayload {
  message: string;
  imageUrls?: string[];
  cards?: RichCardBlock[];
}
