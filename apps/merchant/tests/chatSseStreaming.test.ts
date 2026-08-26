import { describe, expect, it } from 'bun:test';
import { agentEventEmitter } from 'engine';
import { NextRequest } from 'next/server';
import { GET } from '../app/api/store/chat/stream/route';

describe('Storefront Chat SSE Streaming (方案 B)', () => {
  it('should reject request without threadId', async () => {
    const req = new NextRequest('http://localhost:3005/api/store/chat/stream');
    const res = await GET(req);
    expect(res.status).toBe(400);
  });

  it('should establish text/event-stream connection and stream events', async () => {
    const threadId = `test_sse_thread_${Date.now()}`;
    const req = new NextRequest(`http://localhost:3005/api/store/chat/stream?threadId=${threadId}`);
    const res = await GET(req);

    expect(res.status).toBe(200);
    expect(res.headers.get('Content-Type')).toContain('text/event-stream');

    const reader = res.body?.getReader();
    expect(reader).toBeDefined();

    if (reader) {
      // 1. First event should be the 'connected' event
      const { value } = await reader.read();
      const text = new TextDecoder().decode(value);
      expect(text).toContain('event: connected');
      expect(text).toContain(threadId);

      // 2. Simulate an incoming Live Desk reply or AI message event
      const pushPromise = reader.read();
      agentEventEmitter.emit(`thread:${threadId}:message`, {
        id: 'msg_sse_001',
        role: 'assistant',
        content: '[人工客服] 好的张先生，已为您核实完毕！',
        timestamp: new Date().toISOString(),
      });

      const secondRead = await pushPromise;
      const secondText = new TextDecoder().decode(secondRead.value);
      expect(secondText).toContain('event: message');
      expect(secondText).toContain('好的张先生，已为您核实完毕！');

      await reader.cancel();
    }
  });
});
