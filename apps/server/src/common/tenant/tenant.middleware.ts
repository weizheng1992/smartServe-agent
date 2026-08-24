import { Injectable, type NestMiddleware } from '@nestjs/common';
import type { NextFunction, Request, Response } from 'express';
import { type TenantContextPayload, tenantStorage } from './tenant.context';

@Injectable()
export class TenantMiddleware implements NestMiddleware {
  use(req: Request, res: Response, next: NextFunction) {
    const rawTenantId =
      (req.headers['x-tenant-id'] as string) ||
      (req.headers['x-business-id'] as string) ||
      (req.query?.tenantId as string) ||
      (req.query?.businessId as string) ||
      (req.body && typeof req.body === 'object' ? req.body.tenantId || req.body.businessId : undefined) ||
      '';

    const userId = (req.headers['x-user-id'] as string) || (req.query?.userId as string) || 'anonymous';
    const role = (req.headers['x-role'] as string) || 'user';

    const payload: TenantContextPayload = {
      tenantId: (rawTenantId || '').trim(),
      userId: userId.trim(),
      role: role.trim(),
    };

    tenantStorage.run(payload, () => {
      // Also attach to req for convenient controller injection
      (req as any).tenant = payload;
      next();
    });
  }
}
