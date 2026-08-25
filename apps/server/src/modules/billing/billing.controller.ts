import { Body, Controller, Get, HttpCode, HttpStatus, Put } from '@nestjs/common';
import { IsNotEmpty, IsNumber, IsString } from 'class-validator';
import { BillingService } from './billing.service';

export class UpdateQuotaDto {
  @IsNotEmpty()
  @IsString()
  businessId: string;

  @IsNotEmpty()
  @IsNumber()
  monthlyLimitTokens: number;
}

@Controller('api/billing')
export class BillingController {
  constructor(private readonly billingService: BillingService) {}

  @Get('usages')
  async getTenantUsages() {
    const data = await this.billingService.getTenantUsages();
    return {
      success: true,
      data,
    };
  }

  @Put('quota')
  @HttpCode(HttpStatus.OK)
  async updateQuota(@Body() body: UpdateQuotaDto) {
    const data = await this.billingService.updateQuota(body.businessId, body.monthlyLimitTokens);
    return {
      success: true,
      data,
    };
  }
}
