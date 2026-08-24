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

interface AdminTenantState {
  selectedTenantId: string;
  setSelectedTenantId: (tenantId: string) => void;
  getSelectedTenant: () => TenantOption;
}

export const useAdminTenantStore = create<AdminTenantState>((set, get) => ({
  selectedTenantId: 'all',
  setSelectedTenantId: (tenantId: string) => set({ selectedTenantId: tenantId }),
  getSelectedTenant: () => {
    const current = get().selectedTenantId;
    return SUPPORTED_TENANTS.find((t) => t.id === current) || SUPPORTED_TENANTS[0];
  },
}));
