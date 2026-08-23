import { describe, expect, it } from 'bun:test';
import { TenantGuard } from '../src/common/guards/tenant.guard';
import { getTenantContext, getTenantId, tenantStorage } from '../src/common/tenant/tenant.context';
import { TenantMiddleware } from '../src/common/tenant/tenant.middleware';

describe('TenantContext & AsyncLocalStorage Isolation', () => {
  it('should isolate tenant context within async scope', async () => {
    let tenant1Read = '';
    let tenant2Read = '';

    const p1 = new Promise<void>((resolve) => {
      tenantStorage.run({ tenantId: 'nike', userId: 'u_1' }, async () => {
        await new Promise((r) => setTimeout(r, 20));
        tenant1Read = getTenantId();
        expect(getTenantContext()?.userId).toBe('u_1');
        resolve();
      });
    });

    const p2 = new Promise<void>((resolve) => {
      tenantStorage.run({ tenantId: 'apple', userId: 'u_2' }, async () => {
        await new Promise((r) => setTimeout(r, 10));
        tenant2Read = getTenantId();
        expect(getTenantContext()?.userId).toBe('u_2');
        resolve();
      });
    });

    await Promise.all([p1, p2]);

    expect(tenant1Read).toBe('nike');
    expect(tenant2Read).toBe('apple');
  });

  it('should throw error when tenant context is accessed outside store', () => {
    expect(() => getTenantId()).toThrow('Tenant context missing');
  });

  it('TenantGuard should validate presence of tenant context', () => {
    const guard = new TenantGuard();
    tenantStorage.run({ tenantId: 'ecommerce' }, () => {
      const result = guard.canActivate({} as any);
      expect(result).toBe(true);
    });
  });
});
