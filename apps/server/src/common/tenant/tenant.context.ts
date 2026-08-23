import { AsyncLocalStorage } from 'node:async_hooks';

export interface TenantContextPayload {
  tenantId: string;
  userId?: string;
  role?: string;
}

export const tenantStorage = new AsyncLocalStorage<TenantContextPayload>();

export function getTenantContext(): TenantContextPayload | undefined {
  return tenantStorage.getStore();
}

export function getTenantId(): string {
  const store = tenantStorage.getStore();
  if (!store?.tenantId) {
    throw new Error('Tenant context missing: tenantId is not set in current execution context');
  }
  return store.tenantId;
}
