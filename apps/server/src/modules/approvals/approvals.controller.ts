import { Body, Controller, Get, HttpCode, HttpStatus, Post, Query, Req, UseGuards } from '@nestjs/common';
import { IsBoolean, IsNotEmpty, IsOptional, IsString } from 'class-validator';
import type { Request } from 'express';
import { CurrentTenant, TenantGuard } from '../../common/guards/tenant.guard';
import type { TenantContextPayload } from '../../common/tenant/tenant.context';
import { ApprovalsService } from './approvals.service';

export class ProcessApprovalDto {
  @IsOptional()
  @IsString()
  approvalId?: string;

  @IsOptional()
  @IsString()
  threadId?: string;

  @IsNotEmpty()
  @IsString()
  action: string;

  @IsOptional()
  @IsString()
  rejectionReason?: string;

  @IsOptional()
  @IsString()
  humanReply?: string;

  @IsOptional()
  @IsString()
  replyMessage?: string;

  @IsOptional()
  @IsBoolean()
  isFinish?: boolean;
}

@Controller(['api/approvals', 'api/chat/approvals'])
@UseGuards(TenantGuard)
export class ApprovalsController {
  constructor(private readonly approvalsService: ApprovalsService) {}

  @Get()
  async getApprovals(
    @CurrentTenant() tenant: TenantContextPayload,
    @Query('tenantId') queryTenantId?: string,
    @Query('businessId') queryBusinessId?: string,
    @Query('status') status?: string,
    @Query('actionType') actionType?: string,
  ) {
    const tenantId = queryTenantId || queryBusinessId || tenant?.tenantId;

    const approvals = await this.approvalsService.listApprovals(tenantId, status, actionType);

    return {
      success: true,
      approvals,
      total: approvals.length,
      tenantId,
    };
  }

  @Post()
  @HttpCode(HttpStatus.OK)
  async resolveApproval(
    @CurrentTenant() tenant: TenantContextPayload,
    @Body() body: ProcessApprovalDto,
    @Req() req?: Request,
  ) {
    const tenantId =
      tenant?.tenantId || (req?.headers['x-tenant-id'] as string) || (req?.headers['x-business-id'] as string);

    const result = await this.approvalsService.resolveApproval({
      ...body,
      tenantId,
    });

    return result;
  }
}
