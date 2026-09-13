export interface AuditRecord {
  id: string;
  threadId: string;
  businessId: string;
  actionType: string;
  actionPayload: Record<string, any>;
  // resolved_by_human: 人工接管型工单(human_escalation)被人工接管后引擎写入的终态
  status: 'waiting' | 'approved' | 'rejected' | 'timed_out' | 'resolved_by_human';
  reviewerId?: string;
  rejectionReason?: string;
  createdAt: string;
  resolvedAt?: string;
}
