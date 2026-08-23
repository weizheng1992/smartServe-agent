import { type ArgumentsHost, Catch, type ExceptionFilter, HttpException, HttpStatus } from '@nestjs/common';
import type { Request, Response } from 'express';
import { logger } from 'observability';
import { getTenantContext } from '../tenant/tenant.context';

@Catch()
export class HttpExceptionFilter implements ExceptionFilter {
  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();
    const request = ctx.getRequest<Request>();

    const status = exception instanceof HttpException ? exception.getStatus() : HttpStatus.INTERNAL_SERVER_ERROR;

    const exceptionResponse = exception instanceof HttpException ? exception.getResponse() : null;

    let message = 'Internal server error';
    let code = 'INTERNAL_ERROR';

    if (typeof exceptionResponse === 'string') {
      message = exceptionResponse;
    } else if (typeof exceptionResponse === 'object' && exceptionResponse !== null) {
      message = (exceptionResponse as any).message || message;
      code = (exceptionResponse as any).code || (exceptionResponse as any).error || code;
    } else if (exception instanceof Error) {
      message = exception.message;
    }

    const tenantCtx = getTenantContext();

    logger.error(
      {
        err: exception,
        path: request.url,
        method: request.method,
        statusCode: status,
        tenantId: tenantCtx?.tenantId,
        userId: tenantCtx?.userId,
      },
      `[Gateway] Handled Exception: ${message}`,
    );

    response.status(status).json({
      success: false,
      statusCode: status,
      code,
      message,
      tenantId: tenantCtx?.tenantId,
      timestamp: new Date().toISOString(),
      path: request.url,
    });
  }
}
