import { Body, Controller, Get, Param, Post, Query, Req, Res, UseGuards } from '@nestjs/common';
import { ConversationRepository } from 'db';
import type { Request, Response } from 'express';
import { TenantGuard } from '../../common/guards/tenant.guard';
import type { ChatService, DispatchChatDto } from './chat.service';

@Controller('api/chat')
export class ChatController {
  constructor(private readonly chatService: ChatService) {}

  @Post()
  async dispatch(@Body() body: DispatchChatDto, @Req() req: Request) {
    const tenantHeader = (req.headers['x-tenant-id'] as string) || (req.headers['x-business-id'] as string);
    const businessId = body.businessId || tenantHeader || 'ecommerce';

    return this.chatService.dispatchChat({
      ...body,
      businessId,
    });
  }

  @Get(':jobId/stream')
  stream(@Param('jobId') jobId: string, @Res() res: Response) {
    this.chatService.pipeSSE(jobId, res);
  }

  @Get('messages')
  async getMessages(@Query('threadId') threadId: string, @Query('businessId') businessId?: string) {
    if (!threadId) {
      return { success: true, messages: [] };
    }
    const timeline = await ConversationRepository.getConversationTimeline(threadId, businessId);
    return {
      success: true,
      thread: timeline?.thread,
      messages: timeline?.messages || [],
    };
  }

  @Get('orders')
  async getOrders(@Query('userId') userId = 'CUST-8801', @Query('businessId') businessId = 'ecommerce') {
    const orders = await this.chatService.getUserOrders(userId, businessId);
    return {
      success: true,
      orders,
    };
  }
}
