export interface GuardrailRuleRecord {
  id: string;
  ruleName: string;
  ruleType: 'sensitive_keyword' | 'sql_injection' | 'prompt_leakage' | 'model_hallucination';
  pattern: string;
  action: 'block' | 'mask' | 'warn' | 'escalate_hitl';
  severity: 'high' | 'medium' | 'low';
  isEnabled: boolean;
  updatedAt: string;
}
