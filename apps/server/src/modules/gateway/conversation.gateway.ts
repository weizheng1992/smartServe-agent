import { BadRequestException, UsePipes, ValidationPipe } from '@nestjs/common';
import {
  ConnectedSocket,
  MessageBody,
  type OnGatewayConnection,
  type OnGatewayDisconnect,
  SubscribeMessage,
  WebSocketGateway,
  WebSocketServer,
} from '@nestjs/websockets';
import { IsIn, IsNotEmpty, IsOptional, IsString } from 'class-validator';
import { ConversationRepository } from 'db';
import { logger } from 'observability';
import type { Server, Socket } from 'socket.io';
import { redis, useRedis } from 'tools';

export class JoinThreadDto {
  @IsNotEmpty()
  @IsString()
  threadId: string;

  @IsNotEmpty()
  @IsString()
  tenantId: string;

  @IsNotEmpty()
  @IsIn(['user', 'operator'])
  role: 'user' | 'operator';

  @IsOptional()
  @IsString()
  operatorId?: string;

  @IsOptional()
  @IsString()
  operatorName?: string;
}

export class TakeoverDto {
  @IsNotEmpty()
  @IsString()
  threadId: string;

  @IsNotEmpty()
  @IsString()
  tenantId: string;

  @IsNotEmpty()
  @IsString()
  operatorId: string;

  @IsNotEmpty()
  @IsString()
  operatorName: string;
}

export class ReleaseTakeoverDto {
  @IsNotEmpty()
  @IsString()
  threadId: string;

  @IsNotEmpty()
  @IsString()
  tenantId: string;
}

export class ChatMessageDto {
  @IsNotEmpty()
  @IsString()
  threadId: string;

  @IsNotEmpty()
  @IsString()
  tenantId: string;

  @IsNotEmpty()
  @IsIn(['user', 'operator', 'assistant', 'system'])
  role: 'user' | 'operator' | 'assistant' | 'system';

  @IsNotEmpty()
  @IsString()
  content: string;

  @IsOptional()
  cards?: any[];

  @IsOptional()
  operatorInfo?: { operatorId: string; operatorName: string };
}

@WebSocketGateway({
  namespace: '/ws/chat',
  cors: {
    origin: '*',
    credentials: true,
  },
})
export class ConversationGateway implements OnGatewayConnection, OnGatewayDisconnect {
  @WebSocketServer()
  server: Server;

  private connectedClients = new Map<string, { threadId?: string; tenantId?: string; role?: string }>();

  async handleConnection(client: Socket) {
    const auth = client.handshake?.auth || {};
    const headers = client.handshake?.headers || {};
    const query = client.handshake?.query || {};

    const rawTenantId =
      (auth.tenantId as string) ||
      (headers['x-tenant-id'] as string) ||
      (headers['x-business-id'] as string) ||
      (query.tenantId as string) ||
      'ecommerce';

    const cleanTenantId = rawTenantId.trim();
    if (!/^[a-zA-Z0-9_-]{1,64}$/.test(cleanTenantId)) {
      logger.warn({ socketId: client.id, tenantId: cleanTenantId }, '[WS] Rejected connection with invalid tenant');
      client.disconnect(true);
      return;
    }

    logger.info({ socketId: client.id, tenantId: cleanTenantId }, '[WS] Client connected and authenticated');
  }

  handleDisconnect(client: Socket) {
    const meta = this.connectedClients.get(client.id);
    if (meta?.threadId && meta?.tenantId) {
      const room = `tenant:${meta.tenantId}:thread:${meta.threadId}`;
      if (this.server) {
        this.server.to(room).emit('peer_disconnected', {
          socketId: client.id,
          role: meta.role,
          timestamp: new Date().toISOString(),
        });
      }
    }
    this.connectedClients.delete(client.id);
    logger.info({ socketId: client.id }, '[WS] Client disconnected');
  }

  /**
   * 1. 加入会话房间
   */
  @SubscribeMessage('join_thread')
  async handleJoinThread(@ConnectedSocket() client: Socket, @MessageBody() payload: JoinThreadDto) {
    const { threadId, tenantId, role, operatorId, operatorName } = payload;
    const room = `tenant:${tenantId}:thread:${threadId}`;

    await client.join(room);
    this.connectedClients.set(client.id, { threadId, tenantId, role });

    logger.info({ socketId: client.id, threadId, tenantId, role }, '[WS] Joined thread room');

    client.emit('joined_room', { room, threadId, tenantId });

    // 广播房间内有新人接入
    if (this.server) {
      this.server.to(room).emit('peer_joined', {
        socketId: client.id,
        role,
        operatorId,
        operatorName,
        timestamp: new Date().toISOString(),
      });
    }

    // 分布式 Redis 广播通知
    await this.publishWsEvent('peer_joined', room, {
      socketId: client.id,
      role,
      operatorId,
      operatorName,
    });
  }

  /**
   * 2. 人工客服一键接管 (Takeover)
   */
  @SubscribeMessage('takeover_conversation')
  async handleTakeover(@ConnectedSocket() client: Socket, @MessageBody() payload: TakeoverDto) {
    const { threadId, tenantId, operatorId, operatorName } = payload;
    const room = `tenant:${tenantId}:thread:${threadId}`;

    // 更新 DB 状态机 -> human_takeover
    await ConversationRepository.updateConversationStatus({
      threadId,
      businessId: tenantId,
      status: 'human_takeover',
      assignedOperatorId: operatorId,
    });

    // 写入系统消息通知
    const sysMsg = await ConversationRepository.appendMessage({
      threadId,
      businessId: tenantId,
      role: 'system',
      content: `人工客服【${operatorName}】已接入会话，AI 智能体已暂停托管。`,
      operatorInfo: { operatorId, operatorName },
    });

    // 广播房间状态变更
    if (this.server) {
      this.server.to(room).emit('conversation_state_changed', {
        threadId,
        status: 'human_takeover',
        operatorId,
        operatorName,
        systemMessage: sysMsg,
      });
    }

    await this.publishWsEvent('conversation_state_changed', room, {
      threadId,
      status: 'human_takeover',
      operatorId,
      operatorName,
    });
  }

  /**
   * 3. 客服释放接管 -> 归还 AI 托管
   */
  @SubscribeMessage('release_takeover')
  async handleReleaseTakeover(@ConnectedSocket() client: Socket, @MessageBody() payload: ReleaseTakeoverDto) {
    const { threadId, tenantId } = payload;
    const room = `tenant:${tenantId}:thread:${threadId}`;

    await ConversationRepository.updateConversationStatus({
      threadId,
      businessId: tenantId,
      status: 'active',
      assignedOperatorId: null,
    });

    const sysMsg = await ConversationRepository.appendMessage({
      threadId,
      businessId: tenantId,
      role: 'system',
      content: '人工客服已结束接管，已重新切换为 AI 智能助手为您服务。',
    });

    if (this.server) {
      this.server.to(room).emit('conversation_state_changed', {
        threadId,
        status: 'active',
        systemMessage: sysMsg,
      });
    }

    await this.publishWsEvent('conversation_state_changed', room, {
      threadId,
      status: 'active',
    });
  }

  /**
   * 4. 双向发送即时消息
   */
  @SubscribeMessage('send_message')
  async handleSendMessage(@ConnectedSocket() client: Socket, @MessageBody() payload: ChatMessageDto) {
    const { threadId, tenantId, role, content, cards, operatorInfo } = payload;
    const room = `tenant:${tenantId}:thread:${threadId}`;

    const savedMsg = await ConversationRepository.appendMessage({
      threadId,
      businessId: tenantId,
      role,
      content,
      cards,
      operatorInfo,
    });

    const msgPayload = {
      id: savedMsg.id,
      threadId,
      tenantId,
      role,
      content,
      cards,
      operatorInfo,
      timestamp: savedMsg.timestamp || new Date().toISOString(),
    };

    // 全房间广播新消息
    if (this.server) {
      this.server.to(room).emit('new_message', msgPayload);
    }

    await this.publishWsEvent('new_message', room, msgPayload);

    return { success: true, messageId: savedMsg.id };
  }

  /**
   * 辅助方法：统一向分布式 Redis 通道发布 WebSocket 事件
   */
  private async publishWsEvent(event: string, room: string, data: any) {
    if (useRedis && redis) {
      try {
        await redis.publish(
          'ws:events',
          JSON.stringify({
            event,
            room,
            data,
          }),
        );
      } catch (err) {
        logger.warn({ err, event, room }, '[WS] Failed to publish redis ws event');
      }
    }
  }

  /**
   * 5. 正在输入状态广播
   */
  @SubscribeMessage('typing')
  handleTyping(
    @ConnectedSocket() client: Socket,
    @MessageBody()
    payload: {
      threadId: string;
      tenantId: string;
      isTyping: boolean;
      who: string;
    },
  ) {
    const room = `tenant:${payload.tenantId}:thread:${payload.threadId}`;
    client.to(room).emit('user_typing', payload);
  }
}
