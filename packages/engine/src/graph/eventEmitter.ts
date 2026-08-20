import { EventEmitter } from 'node:events';
import type { SSECallback } from 'types';

class AgentEventEmitter extends EventEmitter {
  // Store status updates and result of jobs in memory to support playback
  private journal = new Map<string, { event: string; data: unknown }[]>();
  private results = new Map<string, unknown>();
  private tokenUsage = new Map<string, number>();

  addTokens(jobId: string, tokens: number) {
    if (!jobId) return;
    const current = this.tokenUsage.get(jobId) || 0;
    const next = current + tokens;
    this.tokenUsage.set(jobId, next);
  }

  getTokens(jobId: string): number {
    return this.tokenUsage.get(jobId) || 0;
  }

  emit(event: string, ...args: unknown[]): boolean {
    const parts = event.split(':');
    if (parts.length === 2) {
      const jobId = parts[0];
      const type = parts[1]; // 'status' or 'result'

      if (type === 'status') {
        if (!this.journal.has(jobId)) {
          this.journal.set(jobId, []);
        }
        const data = args[0] as Record<string, unknown> | undefined;
        if (data && typeof data === 'object') {
          data.tokens = this.getTokens(jobId);
        }
        this.journal.get(jobId)!.push({ event, data });
      } else if (type === 'result') {
        const data = args[0] as Record<string, unknown> | undefined;
        if (data && typeof data === 'object') {
          data.tokens = this.getTokens(jobId);
        }
        this.results.set(jobId, data);
      }
    }
    return super.emit(event, ...args);
  }

  // Playback all historical logs for a given jobId to a listener callback
  playbackAndSubscribe(jobId: string, statusCallback: SSECallback, resultCallback: SSECallback) {
    // 1. Playback historical status events in exact sequence
    const logs = this.journal.get(jobId) || [];
    for (const log of logs) {
      statusCallback(log.data);
    }

    // 2. Playback result event if already finished
    if (this.results.has(jobId)) {
      resultCallback(this.results.get(jobId));
      return () => {}; // return empty unsubscribe
    }

    // 3. Otherwise, subscribe to future events live
    const statusHandler = (data: unknown) => statusCallback(data);
    const resultHandler = (data: unknown) => resultCallback(data);

    this.on(`${jobId}:status`, statusHandler);
    this.on(`${jobId}:result`, resultHandler);

    // Return an unsubscribe hook
    return () => {
      this.off(`${jobId}:status`, statusHandler);
      this.off(`${jobId}:result`, resultHandler);
    };
  }

  // Clear memory for a jobId when done to avoid leak
  clearJob(jobId: string) {
    // 延迟 10 秒物理清理内存，确保稍微落后一点的并发请求（例如 5 秒哈希去重期间）
    // 依然能够通过 SSE 连接完美获取到历史状态回放与最终结果，实现 100% 稳定的并发去重！
    setTimeout(() => {
      this.journal.delete(jobId);
      this.results.delete(jobId);
      this.tokenUsage.delete(jobId);
    }, 10000);
  }
}

// Support hot reload persistence in Next.js development server
const globalForEmitter = global as unknown as {
  agentEventEmitter?: AgentEventEmitter;
};

export const agentEventEmitter = globalForEmitter.agentEventEmitter ?? new AgentEventEmitter();

if (process.env.NODE_ENV !== 'production') {
  globalForEmitter.agentEventEmitter = agentEventEmitter;
}
