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
    args?: Record<string, unknown>;
    [key: string]: unknown;
  } | null;
  reason?: string;
  createdAt?: Date | string;
  updatedAt?: Date | string;
  [key: string]: unknown;
}
