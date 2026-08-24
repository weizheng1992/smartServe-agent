import { Controller, Get, UseGuards } from '@nestjs/common';
import { CurrentTenant, TenantGuard } from '../../common/guards/tenant.guard';
import type { TenantContextPayload } from '../../common/tenant/tenant.context';
import { TenantService } from './tenant.service';

@Controller('api/tenant')
@UseGuards(TenantGuard)
export class TenantController {
  constructor(private readonly tenantService: TenantService) {}

  @Get('ping')
  ping(@CurrentTenant() tenant: TenantContextPayload) {
    return {
      success: true,
      message: 'Tenant context active',
      tenant,
      config: this.tenantService.getTenantConfig(tenant.tenantId),
      timestamp: new Date().toISOString(),
    };
  }

  @Get('list')
  listTenants() {
    return {
      success: true,
      tenants: this.tenantService.getAvailableTenants(),
    };
  }
}
