import { create } from 'zustand';

export interface TenantOption {
  id: string;
  name: string;
  badgeColor?: string;
}

export const SUPPORTED_TENANTS: TenantOption[] = [
  {
    id: 'all',
    name: '全平台多租户 (上帝视角)',
    badgeColor: 'bg-slate-100 text-slate-700 border-slate-300',
  },
  {
    id: 'nike',
    name: 'Nike 官方旗舰店',
    badgeColor: 'bg-rose-50 text-rose-700 border-rose-200',
  },
  {
    id: 'adidas',
    name: 'Adidas 运动专营',
    badgeColor: 'bg-blue-50 text-blue-700 border-blue-200',
  },
  {
    id: 'ecommerce',
    name: '通用电商主站',
    badgeColor: 'bg-amber-50 text-amber-700 border-amber-200',
  },
];

const STORAGE_KEY_TENANT_OPTIONS = 'smartserve_admin_supported_tenants';

function getInitialTenants(): TenantOption[] {
  if (typeof window !== 'undefined') {
    try {
      const stored = localStorage.getItem(STORAGE_KEY_TENANT_OPTIONS);
      if (stored) {
        const parsed: TenantOption[] = JSON.parse(stored);
        if (Array.isArray(parsed) && parsed.length > 0) {
          const merged = [...SUPPORTED_TENANTS];
          for (const item of parsed) {
            if (!merged.some((t) => t.id === item.id)) {
              merged.push(item);
            }
          }
          return merged;
        }
      }
    } catch (err) {
      console.warn('[tenantStore] Failed to load custom tenants from localStorage:', err);
    }
  }
  return SUPPORTED_TENANTS;
}

function persistTenants(tenants: TenantOption[]) {
  if (typeof window !== 'undefined') {
    try {
      localStorage.setItem(STORAGE_KEY_TENANT_OPTIONS, JSON.stringify(tenants));
    } catch (err) {
      console.warn('[tenantStore] Failed to persist custom tenants to localStorage:', err);
    }
  }
}

interface AdminTenantState {
  selectedTenantId: string;
  tenants: TenantOption[];
  setSelectedTenantId: (tenantId: string) => void;
  getSelectedTenant: () => TenantOption;
  addOrUpdateTenant: (tenant: TenantOption) => void;
  removeTenant: (tenantId: string) => void;
}

export const useAdminTenantStore = create<AdminTenantState>((set, get) => ({
  selectedTenantId: 'all',
  tenants: getInitialTenants(),
  setSelectedTenantId: (tenantId: string) => set({ selectedTenantId: tenantId }),
  getSelectedTenant: () => {
    const current = get().selectedTenantId;
    const list = get().tenants;
    return list.find((t) => t.id === current) || list[0] || SUPPORTED_TENANTS[0];
  },
  addOrUpdateTenant: (newTenant: TenantOption) => {
    const list = get().tenants;
    const exists = list.some((t) => t.id === newTenant.id);
    let updated: TenantOption[];
    if (exists) {
      updated = list.map((t) => (t.id === newTenant.id ? { ...t, ...newTenant } : t));
    } else {
      updated = [...list, newTenant];
    }
    persistTenants(updated);
    set({ tenants: updated });
  },
  removeTenant: (tenantId: string) => {
    if (tenantId === 'all' || tenantId === 'ecommerce') return;
    const list = get().tenants;
    const updated = list.filter((t) => t.id !== tenantId);
    persistTenants(updated);
    set({
      tenants: updated,
      selectedTenantId: get().selectedTenantId === tenantId ? 'all' : get().selectedTenantId,
    });
  },
}));
