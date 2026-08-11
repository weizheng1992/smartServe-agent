export interface Approval {
  id: string;
  threadId: string;
  actionType: string;
  actionPayload: Record<string, unknown> | null;
  status: "waiting" | "approved" | "rejected" | "expired" | "cancelled";
  deadline: string;
  createdAt: string;
  businessId?: string;
}

export interface PreferenceFact {
  id: string;
  userId: string;
  fact: string;
  confidence: number;
  status: "approved" | "pending" | "rejected";
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
