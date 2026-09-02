import { describe, expect, it, mock } from 'bun:test';
import { agentEventEmitter } from 'engine';
import { ChatService } from '../src/modules/chat/chat.service';
import { waitFor } from './helpers/waitFor';

describe('⚡ Resilient SSE Stream Pipeline & Sequence IDs Suite', () => {
  it('should set appropriate SSE headers and emit sequenced events', async () => {
    const service = new ChatService();
    const jobId = `job_sse_test_${Date.now()}`;
    const writtenChunks: string[] = [];
    const headers: Record<string, string> = {};

    let closeHandler: (() => void) | null = null;

    const mockRes: any = {
      setHeader: (k: string, v: string) => {
        headers[k] = v;
      },
      flushHeaders: mock(() => {}),
      write: mock((chunk: string) => {
        writtenChunks.push(chunk);
      }),
      end: mock(() => {}),
      on: (event: string, cb: () => void) => {
        if (event === 'close') closeHandler = cb;
      },
    };

    service.pipeSSE(jobId, mockRes);

    expect(headers['Content-Type']).toBe('text/event-stream');
    expect(headers['Cache-Control']).toContain('no-cache');
    expect(headers.Connection).toBe('keep-alive');

    // Emit thoughts & results via agentEventEmitter。
    // Phase 1 起 Redis 可用时走事件流路径,投递为毫秒级异步,统一 waitFor 收数。
    agentEventEmitter.emit('thought', {
      jobId,
      step: '正在查询订单详情',
    });

    agentEventEmitter.emit('result', {
      jobId,
      output: '查询完成，订单正在派送中。',
      cards: [{ type: 'order_status', title: '订单状态' }],
    });

    // thought(seq 1) → cards(seq 2) → result(seq 3)
    await waitFor(() => writtenChunks.length >= 3);
    expect(writtenChunks.some((c) => c.includes('event: thought') && c.includes('id: 1'))).toBe(true);
    expect(writtenChunks.some((c) => c.includes('event: cards'))).toBe(true);
    expect(writtenChunks.some((c) => c.includes('event: result'))).toBe(true);

    // Trigger close
    if (closeHandler) {
      (closeHandler as () => void)();
    }
  });
});
