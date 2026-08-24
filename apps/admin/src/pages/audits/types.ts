export interface AuditRecord {
  id: string;
  threadId: string;
  businessId: string;
  actionType: string;
  actionPayload: Record<string, any>;
  status: 'waiting' | 'approved' | 'rejected' | 'timed_out';
  reviewerId?: string;
  rejectionReason?: string;
  createdAt: string;
  resolvedAt?: string;
}
