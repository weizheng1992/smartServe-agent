import { Controller, Get, Headers, Query } from '@nestjs/common';
import { SystemLogsService } from './system-logs.service';

@Controller('api/logs')
export class SystemLogsController {
  constructor(private readonly systemLogsService: SystemLogsService) {}

  @Get()
  async getLogs(
    @Query('tenantId') tenantQuery?: string,
    @Query('level') level?: string,
    @Query('limit') limitStr?: string,
    @Headers('x-tenant-id') tenantHeader?: string,
  ) {
    const tenantId = tenantQuery || tenantHeader;
    const limit = limitStr ? Number.parseInt(limitStr, 10) : 50;
    const data = await this.systemLogsService.getLogs({
      tenantId,
      level,
      limit,
    });
    return {
      success: true,
      tenantId: tenantId || 'all',
      total: data.length,
      data,
    };
  }
}
