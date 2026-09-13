export interface TenantRecord {
  id: string;
  name: string;
  industry: string;
  channel: string;
  apiKey: string;
  refundLimit: number;
  autoEscalation: boolean;
  webhookUrl: string;
  status: 'active' | 'disabled';
  /** builtin = 内置业务域(评测/契约依赖基线):禁删禁停用(admin-readiness 02) */
  planTier?: 'free' | 'builtin' | string;
  createdAt: string;
  /** 租户引导配置(tenant_configs.onboarding_config 回读,null = 未配置走平台默认) */
  onboardingConfig?: Record<string, any> | null;
  /** 编辑态专用:JSON 文本域的字符串形态(handleOpenEdit 序列化填充,提交时解析) */
  onboardingConfigJson?: string;
}
