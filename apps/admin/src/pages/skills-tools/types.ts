export interface SkillToolRecord {
  id: string;
  name: string;
  type: 'native' | 'openapi' | 'mcp' | 'skill';
  description: string;
  riskLevel: 'low' | 'medium' | 'high';
  requiresHitl: boolean;
  tenantScope: string;
  status: 'enabled' | 'disabled';
  approvalThresholdAmount?: number;
}
