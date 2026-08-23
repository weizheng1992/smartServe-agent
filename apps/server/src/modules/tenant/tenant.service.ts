import { Injectable } from '@nestjs/common';
import { TenantRegistryService } from 'business-configs';

@Injectable()
export class TenantService {
  async getTenantConfig(tenantId: string) {
    return TenantRegistryService.getTenantConfig(tenantId);
  }

  getAvailableTenants() {
    return [
      { id: 'ecommerce', name: '官方综合商城', industry: 'E-commerce' },
      { id: 'nike', name: 'Nike 官方旗舰店', industry: 'Footwear & Apparel' },
      {
        id: 'apple',
        name: 'Apple 官方授权店',
        industry: 'Consumer Electronics',
      },
      { id: 'ikea', name: '宜家家居官方旗舰店', industry: 'Home & Furniture' },
    ];
  }
}
