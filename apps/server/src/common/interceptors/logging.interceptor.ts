import { type CallHandler, type ExecutionContext, Injectable, type NestInterceptor } from '@nestjs/common';
import { logger } from 'observability';
import type { Observable } from 'rxjs';
import { tap } from 'rxjs/operators';
import { getTenantContext } from '../tenant/tenant.context';

@Injectable()
export class LoggingInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<any> {
    const req = context.switchToHttp().getRequest();
    const startTime = Date.now();
    const tenantCtx = getTenantContext();

    return next.handle().pipe(
      tap({
        next: () => {
          const duration = Date.now() - startTime;
          logger.info(
            {
              method: req.method,
              url: req.url,
              durationMs: duration,
              tenantId: tenantCtx?.tenantId,
              userId: tenantCtx?.userId,
            },
            `[Gateway] ${req.method} ${req.url} completed in ${duration}ms`,
          );
        },
        error: (err) => {
          const duration = Date.now() - startTime;
          logger.warn(
            {
              method: req.method,
              url: req.url,
              durationMs: duration,
              tenantId: tenantCtx?.tenantId,
              error: err.message,
            },
            `[Gateway] ${req.method} ${req.url} failed after ${duration}ms`,
          );
        },
      }),
    );
  }
}
