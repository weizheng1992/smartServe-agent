import { describe, expect, it } from 'bun:test';
import { ChatService } from '../src/modules/chat/chat.service';

describe('ChatService NestJS Integration', () => {
  it('should reject empty message', async () => {
    const service = new ChatService();
    expect(service.dispatchChat({ message: '   ' })).rejects.toThrow('Message is required');
  });

  it('should dispatch synchronous chat request and return results and threadId', async () => {
    const service = new ChatService();
    const threadId = `nest_test_${Date.now()}`;

    const res = await service.dispatchChat({
      message: '你好，请问你们支持哪些服务？',
      threadId,
      userId: 'u_nest_tester',
      businessId: 'ecommerce',
      sync: true,
    });

    expect(res.success).toBe(true);
    expect(res.threadId).toBe(threadId);
    expect(res.output).toBeDefined();
    expect(typeof res.output).toBe('string');
  }, 30000);
});
