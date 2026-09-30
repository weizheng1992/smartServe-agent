export interface PersonaRecord {
  id: string;
  userId: string;
  businessId: string;
  /** 生效作用域:global 全员可见(具名租户视图只读附带),tenant 本店私有 */
  scope?: 'global' | 'tenant';
  fact: string;
  confidence: number;
  source: string;
  status: 'approved' | 'pending' | 'rejected';
  createdAt: string;
}
