import { Body, Controller, Get, Param, Post, Query, Req, UseGuards } from '@nestjs/common';
import { IsArray, IsNotEmpty, IsOptional, IsString } from 'class-validator';
import { ConversationRepository } from 'db';
import type { Request } from 'express';
import { TenantGuard } from '../../common/guards/tenant.guard';

export class UpdateConversationStatusDto {
  @IsNotEmpty()
  @IsString()
  status: string;

  @IsOptional()
  @IsString()
  assignedOperatorId?: string;

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  tags?: string[];
}

@Controller('api/conversations')
@UseGuards(TenantGuard)
export class ConversationsController {
  @Get()
  async listConversations(
    @Query('status') status?: string,
    @Query('tag') tag?: string,
    @Query('search') searchKeyword?: string,
    @Query('limit') limit?: string,
    @Query('offset') offset?: string,
    @Req() req?: Request,
  ) {
    const tenantId =
      (req?.headers['x-tenant-id'] as string) ||
      (req?.headers['x-business-id'] as string) ||
      (req?.query?.tenantId as string) ||
      'ecommerce';

    const res = await ConversationRepository.listConversations({
      businessId: tenantId,
      status: status === 'all' ? undefined : status,
      tag,
      searchKeyword,
      limit: limit ? Number.parseInt(limit, 10) : 20,
      offset: offset ? Number.parseInt(offset, 10) : 0,
    });

    return {
      success: true,
      tenantId,
      ...res,
    };
  }

  @Get(':threadId')
  async getConversation(@Param('threadId') threadId: string, @Req() req?: Request) {
    const tenantId =
      (req?.headers['x-tenant-id'] as string) ||
      (req?.headers['x-business-id'] as string) ||
      (req?.query?.tenantId as string);

    const timeline = await ConversationRepository.getConversationTimeline(threadId, tenantId);

    return {
      success: true,
      data: timeline,
    };
  }

  @Post(':threadId/status')
  async updateStatus(
    @Param('threadId') threadId: string,
    @Body()
    body: UpdateConversationStatusDto,
    @Req() req?: Request,
  ) {
    const tenantId =
      (req?.headers['x-tenant-id'] as string) || (req?.headers['x-business-id'] as string) || 'ecommerce';

    const updated = await ConversationRepository.updateConversationStatus({
      threadId,
      businessId: tenantId,
      status: body.status,
      assignedOperatorId: body.assignedOperatorId,
      tags: body.tags,
    });

    return {
      success: true,
      data: updated,
    };
  }
}
