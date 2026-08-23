import {
  ConnectedSocket,
  MessageBody,
  type OnGatewayConnection,
  type OnGatewayDisconnect,
  SubscribeMessage,
  WebSocketGateway,
  WebSocketServer,
} from '@nestjs/websockets';
import { ConversationRepository } from 'db';
import { logger } from 'observability';
import type { Server, Socket } from 'socket.io';

export interface JoinThreadDto {
  threadId: string;
  tenantId: string;
  role: 'user' | 'operator';
  operatorId?: string;
  operatorName?: string;
}

export interface TakeoverDto {
  threadId: string;
  tenantId: string;
  operatorId: string;
  operatorName: string;
}

export interface ReleaseTakeoverDto {
  threadId: string;
  tenantId: string;
}

export interface ChatMessageDto {
  threadId: string;
  tenantId: string;
  role: 'user' | 'operator' | 'assistant';
  content: string;
  cards?: any[];
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

  handleConnection(client: Socket) {
    logger.info({ socketId: client.id }, '[WS] Client connected');
  }

  handleDisconnect(client: Socket) {
    const meta = this.connectedClients.get(client.id);
    if (meta?.threadId && meta?.tenantId) {
      const room = `tenant:${meta.tenantId}:thread:${meta.threadId}`;
      this.server.to(room).emit('peer_disconnected', {
        socketId: client.id,
        role: meta.role,
      });
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
    this.server.to(room).emit('peer_joined', {
      socketId: client.id,
      role,
      operatorId,
      operatorName,
      timestamp: new Date().toISOString(),
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
    this.server.to(room).emit('conversation_state_changed', {
      threadId,
      status: 'human_takeover',
      operatorId,
      operatorName,
      systemMessage: sysMsg,
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

    this.server.to(room).emit('conversation_state_changed', {
      threadId,
      status: 'active',
      systemMessage: sysMsg,
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

    // 全房间广播新消息
    this.server.to(room).emit('new_message', {
      id: savedMsg.id,
      threadId,
      tenantId,
      role,
      content,
      cards,
      operatorInfo,
      timestamp: savedMsg.timestamp || new Date().toISOString(),
    });

    return { success: true, messageId: savedMsg.id };
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
