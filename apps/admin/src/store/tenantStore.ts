import { create } from 'zustand';
import { tenantsApi } from '../lib/api';

export interface TenantOption {
  id: string;
  name: string;
  badgeColor?: string;
}

/** 唯一内置选项:全平台上帝视角;真实租户列表由 /api/tenant/list 动态加载 */
export const SUPPORTED_TENANTS: TenantOption[] = [
  {
    id: 'all',
    name: '全平台多租户 (上帝视角)',
    badgeColor: 'bg-slate-100 text-slate-700 border-slate-300',
  },
];

const TENANT_BADGE_PALETTE = [
  'bg-rose-50 text-rose-700 border-rose-200',
  'bg-blue-50 text-blue-700 border-blue-200',
  'bg-amber-50 text-amber-700 border-amber-200',
];

interface AdminTenantState {
  selectedTenantId: string;
  tenants: TenantOption[];
  setSelectedTenantId: (tenantId: string) => void;
  getSelectedTenant: () => TenantOption;
  loadTenantsFromServer: () => Promise<void>;
  addOrUpdateTenant: (tenant: TenantOption) => void;
  removeTenant: (tenantId: string) => void;
}

export const useAdminTenantStore = create<AdminTenantState>((set, get) => ({
  selectedTenantId: 'all',
  tenants: SUPPORTED_TENANTS,
  setSelectedTenantId: (tenantId: string) => set({ selectedTenantId: tenantId }),
  getSelectedTenant: () => {
    const current = get().selectedTenantId;
    const list = get().tenants;
    return list.find((t) => t.id === current) || list[0] || SUPPORTED_TENANTS[0];
  },
  // 从 /api/tenant/list 加载真实注册租户;失败时保持现有列表(仅"全平台"选项)
  loadTenantsFromServer: async () => {
    try {
      const res = await tenantsApi.list();
      if (res.success && Array.isArray(res.tenants)) {
        const remote: TenantOption[] = res.tenants
          .filter((t: any) => t.id && (t.status || 'active') === 'active')
          .map((t: any, idx: number) => ({
            id: String(t.id),
            name: t.name || String(t.id),
            badgeColor: TENANT_BADGE_PALETTE[idx % TENANT_BADGE_PALETTE.length],
          }));
        set({ tenants: [...SUPPORTED_TENANTS, ...remote] });
      }
    } catch (err) {
      console.warn('[tenantStore] Failed to load tenants from server:', err);
    }
  },
  addOrUpdateTenant: (newTenant: TenantOption) => {
    const list = get().tenants;
    const exists = list.some((t) => t.id === newTenant.id);
    const updated = exists
      ? list.map((t) => (t.id === newTenant.id ? { ...t, ...newTenant } : t))
      : [...list, newTenant];
    set({ tenants: updated });
  },
  removeTenant: (tenantId: string) => {
    if (tenantId === 'all') return;
    const list = get().tenants;
    set({
      tenants: list.filter((t) => t.id !== tenantId),
      selectedTenantId: get().selectedTenantId === tenantId ? 'all' : get().selectedTenantId,
    });
  },
}));
