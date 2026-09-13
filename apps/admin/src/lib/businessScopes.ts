import type { TenantOption } from '../store/tenantStore';

/**
 * 平台内置业务域:数据模型中真实存在、但独立于 SaaS 租户注册表(tenants 表)的
 * business 作用域 —— engine 双屋画像/记忆体系约定:ecommerce 为平台自有主站租户,
 * global 为跨租户记忆层;nike/adidas 为引擎 seed 内置演示商户(有真实用量与知识数据)。
 * 租户注册表当前仅含入驻商户(如 aurora),注册表 ∪ 内置域才是可归属的完整业务域。
 */
export const BUILTIN_BUSINESS_SCOPES: TenantOption[] = [
  { id: 'ecommerce', name: '通用电商主站 (SaaS 平台自有)' },
  { id: 'global', name: '全局画像记忆层 (GLOBAL)' },
  { id: 'nike', name: 'Nike 官方旗舰店 (内置演示商户)' },
  { id: 'adidas', name: 'Adidas 运动专营 (内置演示商户)' },
];

/** 表单「归属商户」下拉选项:注册表租户优先,内置业务域补位,按 id 去重 */
export function buildBusinessScopeOptions(tenants: TenantOption[]): TenantOption[] {
  const registry = tenants.filter((t) => t.id !== 'all');
  const seen = new Set(registry.map((t) => t.id));
  return [...registry, ...BUILTIN_BUSINESS_SCOPES.filter((scope) => !seen.has(scope.id))];
}
