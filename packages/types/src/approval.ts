export type ApprovalStatus = 'pending' | 'waiting' | 'approved' | 'rejected' | 'cancelled' | 'expired' | string;

export interface ApprovalActionPayload {
  orderId?: string;
  refundAmount?: number | string;
  rejectionReason?: string;
  reason?: string;
  description?: string;
  args?: Record<string, unknown>;
  userInput?: string;
  triggerSource?: string;
  stepIndex?: number;
  [key: string]: unknown;
}

export interface PendingApprovalRecord {
  id: string;
  threadId: string;
  userId?: string | null;
  userEmail?: string | null;
  businessId?: string | null;
  status: ApprovalStatus;
  actionType?: string | null;
  actionPayload?: ApprovalActionPayload | Record<string, unknown> | null;
  reason?: string | null;
  deadline?: Date | string | null;
  createdAt?: Date | string | null;
  updatedAt?: Date | string | null;
  [key: string]: unknown;
}

export type Approval = PendingApprovalRecord;

export interface ApprovalDecisionRequest {
  approvalId: string;
  action: 'approve' | 'reject' | 'cancel' | 'reply';
  rejectionReason?: string;
  replyMessage?: string;
  isFinish?: boolean;
}

export interface OrderItemSummary {
  productName: string;
  price: number;
  quantity: number;
  imageUrl?: string;
}

export interface UserOrderRecord {
  orderId: string;
  status: string;
  totalAmount: number;
  currency?: string;
  carrier?: string;
  trackingNumber?: string;
  addressId?: string;
  addressTag?: string;
  recipientName?: string;
  phone?: string;
  shippingAddress?: string;
  estimatedDelivery?: string;
  createdAt?: string;
  businessId?: string;
  items?: OrderItemSummary[];
}
