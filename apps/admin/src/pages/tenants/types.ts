export interface TenantRecord {
  id: string;
  name: string;
  industry: string;
  channel: string;
  apiKey: string;
  refundLimit: number;
  autoEscalation: boolean;
  webhookUrl: string;
  status: "active" | "disabled";
  createdAt: string;
}
