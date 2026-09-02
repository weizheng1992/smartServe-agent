/**
 * ConversationGateway WebSocket & Takeover State Machine(密封版)
 *
 * Phase 0 改造:ConversationRepository / ConversationGateway 延迟到
 * 容器 env 注入后动态导入;断言与原版完全一致。
 */
import { beforeAll, describe, expect, it, mock } from 'bun:test';
import { type SealedEnv, initSealedEnv, loadDb } from './helpers/sealedEnv';

let sealed: SealedEnv;
let ConversationRepository: typeof import('db')['ConversationRepository'];
let ConversationGateway: typeof import('../src/modules/gateway/conversation.gateway')['ConversationGateway'];

describe('ConversationGateway WebSocket & Takeover State Machine', () => {
  beforeAll(async () => {
    sealed = await initSealedEnv();
    ({ ConversationRepository } = await loadDb());
    ({ ConversationGateway } = await import('../src/modules/gateway/conversation.gateway'));
  });

  it('should process takeover_conversation and broadcast state change', async () => {
    const gateway = new ConversationGateway();
    const mockEmittedEvents: Array<{ event: string; data: any }> = [];

    const mockServer: any = {
      to: (room: string) => ({
        emit: (event: string, data: any) => {
          mockEmittedEvents.push({ event, data });
        },
      }),
    };
    gateway.server = mockServer;

    const mockSocket: any = {
      id: 'socket_operator_1',
      join: mock(() => Promise.resolve()),
      emit: mock(() => {}),
      to: () => ({ emit: () => {} }),
    };

    const testThread = `ws_thread_test_${Date.now()}`;
    const tenantId = 'nike';

    // 1. Join room
    await gateway.handleJoinThread(mockSocket, {
      threadId: testThread,
      tenantId,
      role: 'operator',
      operatorId: 'op_999',
      operatorName: '高级客服小王',
    });

    expect(mockSocket.join).toHaveBeenCalled();

    // 2. Perform Takeover
    await gateway.handleTakeover(mockSocket, {
      threadId: testThread,
      tenantId,
      operatorId: 'op_999',
      operatorName: '高级客服小王',
    });

    expect(mockEmittedEvents.some((e) => e.event === 'conversation_state_changed')).toBe(true);

    const stateEvent = mockEmittedEvents.find((e) => e.event === 'conversation_state_changed');
    expect(stateEvent?.data.status).toBe('human_takeover');
    expect(stateEvent?.data.operatorName).toBe('高级客服小王');

    // 3. Send operator message
    const sendRes = await gateway.handleSendMessage(mockSocket, {
      threadId: testThread,
      tenantId,
      role: 'operator',
      content: '您好，我是人工客服小王，请问有什么可以帮您？',
      operatorInfo: { operatorId: 'op_999', operatorName: '高级客服小王' },
    });

    expect(sendRes.success).toBe(true);
    expect(mockEmittedEvents.some((e) => e.event === 'new_message')).toBe(true);

    // 4. Check DB status
    const timeline = await ConversationRepository.getConversationTimeline(testThread, tenantId);
    expect(timeline?.thread.status).toBe('human_takeover');
    expect(timeline?.thread.assignedOperatorId).toBe('op_999');
    expect(timeline?.messages.some((m) => m.role === 'operator')).toBe(true);
  });
});
