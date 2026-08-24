export interface TenantBillingRecord {
  businessId: string;
  tenantName: string;
  totalTokens: number;
  monthlyLimitTokens: number;
  costUsd: number;
  sessionsCount: number;
  autopilotRate: number;
  billingStatus: 'normal' | 'warning' | 'exceeded';
}
