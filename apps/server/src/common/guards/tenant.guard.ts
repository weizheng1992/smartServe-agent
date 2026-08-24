import {
  BadRequestException,
  type CanActivate,
  type ExecutionContext,
  Injectable,
  UnauthorizedException,
  createParamDecorator,
} from '@nestjs/common';
import { type TenantContextPayload, getTenantContext } from '../tenant/tenant.context';

@Injectable()
export class TenantGuard implements CanActivate {
  canActivate(context: ExecutionContext): boolean {
    const ctx = getTenantContext();
    if (!ctx || !ctx.tenantId || ctx.tenantId.trim() === '') {
      throw new UnauthorizedException({
        code: 'TENANT_CONTEXT_MISSING',
        message: 'Missing or invalid tenant identifier (x-tenant-id / x-business-id header required)',
      });
    }

    const tenantId = ctx.tenantId.trim();
    // 租户标识安全格式校验（仅允许字母、数字、下划线、中划线，长度 1-64）
    if (!/^[a-zA-Z0-9_-]{1,64}$/.test(tenantId)) {
      throw new BadRequestException({
        code: 'INVALID_TENANT_ID_FORMAT',
        message: `Tenant identifier '${tenantId}' contains invalid characters or exceeds 64 characters`,
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
