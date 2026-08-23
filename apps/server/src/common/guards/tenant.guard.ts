import {
  BadRequestException,
  type CanActivate,
  type ExecutionContext,
  Injectable,
  createParamDecorator,
} from '@nestjs/common';
import { type TenantContextPayload, getTenantContext } from '../tenant/tenant.context';

@Injectable()
export class TenantGuard implements CanActivate {
  canActivate(context: ExecutionContext): boolean {
    const ctx = getTenantContext();
    if (!ctx || !ctx.tenantId || ctx.tenantId.trim() === '') {
      throw new BadRequestException({
        code: 'TENANT_CONTEXT_MISSING',
        message: 'Missing or invalid tenant identifier (x-tenant-id / x-business-id)',
      });
    }
    return true;
  }
}

export const CurrentTenant = createParamDecorator(
  (data: keyof TenantContextPayload | undefined, ctx: ExecutionContext) => {
    const store = getTenantContext();
    if (!store) return undefined;
    return data ? store[data] : store;
  },
);
