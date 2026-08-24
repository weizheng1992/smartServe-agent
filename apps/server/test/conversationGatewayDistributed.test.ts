import { describe, expect, it, mock } from 'bun:test';
import { ConversationGateway } from '../src/modules/gateway/conversation.gateway';

describe('🌐 Distributed WebSocket Gateway & Handshake Auth Suite', () => {
  it('should accept connection with valid tenant in handshake auth', async () => {
    const gateway = new ConversationGateway();
    let disconnected = false;

    const mockSocket: any = {
      id: 'sock_valid_1',
      handshake: {
        auth: { tenantId: 'adidas', userId: 'user_100' },
        headers: {},
        query: {},
      },
      disconnect: mock(() => {
        disconnected = true;
      }),
    };

    await gateway.handleConnection(mockSocket);
    expect(disconnected).toBe(false);
  });

  it('should reject and disconnect socket with invalid tenant format or SQL injection attempt', async () => {
    const gateway = new ConversationGateway();
    let disconnected = false;

    const mockSocket: any = {
      id: 'sock_malicious_1',
      handshake: {
        auth: { tenantId: "nike' OR '1'='1" },
        headers: {},
        query: {},
      },
      disconnect: mock(() => {
        disconnected = true;
      }),
    };

    await gateway.handleConnection(mockSocket);
    expect(disconnected).toBe(true);
    expect(mockSocket.disconnect).toHaveBeenCalled();
  });

  it('should handle peer disconnect and cleanup client mapping', async () => {
    const gateway = new ConversationGateway();
    const emittedEvents: Array<{ event: string; data: any }> = [];

    gateway.server = {
      to: (room: string) => ({
        emit: (event: string, data: any) => {
          emittedEvents.push({ event, data });
        },
      }),
    } as any;

    const mockSocket: any = {
      id: 'sock_disconnect_1',
      join: mock(() => Promise.resolve()),
      emit: mock(() => {}),
    };

    await gateway.handleJoinThread(mockSocket, {
      threadId: 't_cleanup_99',
      tenantId: 'nike',
      role: 'user',
    });

    gateway.handleDisconnect(mockSocket);
    expect(emittedEvents.some((e) => e.event === 'peer_disconnected')).toBe(true);
  });
});
