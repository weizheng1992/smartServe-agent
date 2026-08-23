export interface SkillToolRecord {
  id: string;
  name: string;
  type: "native" | "openapi" | "mcp";
  description: string;
  riskLevel: "low" | "medium" | "high";
  requiresHitl: boolean;
  tenantScope: string;
  status: "enabled" | "disabled";
}
