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
  businessId?: string;
  status: ApprovalStatus;
  actionType?: string;
  actionPayload?: ApprovalActionPayload | Record<string, unknown> | null;
  reason?: string;
  deadline?: Date | string;
  createdAt?: Date | string;
  updatedAt?: Date | string;
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
