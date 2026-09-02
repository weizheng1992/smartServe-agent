import { EventEmitter } from 'node:events';
import { publishAgentEvent } from 'tools';
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

    // Phase 1 事件主干:job 级事件同步镜像发布到 Redis Streams,使跨进程
    // (Temporal worker / 未来的 engine-py)消费方与本地监听者看到同一事件流。
    // Redis 不可用时 publishAgentEvent 内部静默跳过,进程内行为不变。
    this.mirrorToEventBus(event, args[0]);

    return super.emit(event, ...args);
  }

  /**
   * 将 job 级事件镜像到 Redis Streams 总线。两种既有事件词汇均覆盖:
   * - 名称空间式 `jobId:status` / `jobId:result`
   * - 载荷式 `thought` / `tool` / `result` / ...({ jobId, ... })
   * result 事件先发布 cards 拆分事件再发布自身,保持
   * "cards → result" 的线上顺序与递增 id 序列(与原服务端拆分逻辑一致)。
   */
  private mirrorToEventBus(event: string, arg0: unknown): void {
    const namespaced = event.split(':');
    if (namespaced.length === 2) {
      void publishAgentEvent(namespaced[0], namespaced[1], arg0);
      return;
    }
    const payload = arg0 as { jobId?: string; cards?: unknown[] } | undefined;
    if (!payload || typeof payload !== 'object' || typeof payload.jobId !== 'string' || !payload.jobId) {
      return;
    }
    void (async () => {
      if (event === 'result' && Array.isArray(payload.cards) && payload.cards.length > 0) {
        await publishAgentEvent(payload.jobId, 'cards', { cards: payload.cards });
      }
      await publishAgentEvent(payload.jobId, event, payload);
    })();
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
