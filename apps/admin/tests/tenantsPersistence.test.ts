import { beforeEach, describe, expect, it } from 'bun:test';
import { useAdminTenantStore } from '../src/store/tenantStore';

describe('Admin Tenants Management & Persistence', () => {
  beforeEach(() => {
    // Reset store state
    useAdminTenantStore.setState({
      selectedTenantId: 'all',
      tenants: [
        { id: 'all', name: '全平台多租户 (上帝视角)' },
        { id: 'nike', name: 'Nike 官方旗舰店' },
        { id: 'adidas', name: 'Adidas 运动专营' },
        { id: 'ecommerce', name: '通用电商主站' },
      ],
    });
  });

  it('should dynamically add a new merchant and retrieve it', () => {
    const store = useAdminTenantStore.getState();
    store.addOrUpdateTenant({
      id: 'aurora',
      name: '极光潮品官方旗舰店',
      badgeColor: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    });

    const updated = useAdminTenantStore.getState();
    const aurora = updated.tenants.find((t) => t.id === 'aurora');
    expect(aurora).toBeDefined();
    expect(aurora?.name).toBe('极光潮品官方旗舰店');

    // Test selection
    updated.setSelectedTenantId('aurora');
    expect(useAdminTenantStore.getState().getSelectedTenant().id).toBe('aurora');
  });

  it('should update existing merchant details', () => {
    const store = useAdminTenantStore.getState();
    store.addOrUpdateTenant({
      id: 'nike',
      name: 'Nike 旗舰超级店 (Updated)',
    });

    const updated = useAdminTenantStore.getState();
    const nike = updated.tenants.find((t) => t.id === 'nike');
    expect(nike?.name).toBe('Nike 旗舰超级店 (Updated)');
  });

  it('should remove tenant and reset selection if active', () => {
    const store = useAdminTenantStore.getState();
    store.addOrUpdateTenant({ id: 'temp_shop', name: '临时商户' });
    store.setSelectedTenantId('temp_shop');
    expect(useAdminTenantStore.getState().selectedTenantId).toBe('temp_shop');

    store.removeTenant('temp_shop');
    const updated = useAdminTenantStore.getState();
    expect(updated.tenants.find((t) => t.id === 'temp_shop')).toBeUndefined();
    expect(updated.selectedTenantId).toBe('all');
  });
});
