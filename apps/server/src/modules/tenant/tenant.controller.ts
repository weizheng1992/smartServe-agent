import { Body, Controller, Delete, Get, Param, Post, UseGuards } from '@nestjs/common';
import { CurrentTenant, TenantGuard } from '../../common/guards/tenant.guard';
import type { TenantContextPayload } from '../../common/tenant/tenant.context';
import { TenantService } from './tenant.service';

@Controller('api/tenant')
export class TenantController {
  constructor(private readonly tenantService: TenantService) {}

  @Get('ping')
  @UseGuards(TenantGuard)
  async ping(@CurrentTenant() tenant: TenantContextPayload) {
    return {
      success: true,
      message: 'Tenant context active',
      tenant,
      config: await this.tenantService.getTenantConfig(tenant.tenantId),
      timestamp: new Date().toISOString(),
    };
  }

  @Get('list')
  async listTenants() {
    return {
      success: true,
      tenants: await this.tenantService.getAvailableTenants(),
    };
  }

  @Post()
  async createTenant(@Body() body: any) {
    return this.tenantService.createTenant(body);
  }

  @Delete(':id')
  async deleteTenant(@Param('id') id: string) {
    return this.tenantService.deleteTenant(id);
  }
}
