import type { Approval, PendingApprovalRecord } from 'types';

export type { Approval, PendingApprovalRecord };

export interface PreferenceFact {
  id: string;
  userId: string;
  fact: string;
  confidence: number;
  status: 'approved' | 'pending' | 'rejected';
  source: string;
  createdAt: string;
  businessId: string;
}

export interface AnalyticsSummary {
  totalCostUsd: number;
  totalSessions: number;
  avgLatencyMs: number;
  avgTokens: number;
  autopilotRate: number;
}
