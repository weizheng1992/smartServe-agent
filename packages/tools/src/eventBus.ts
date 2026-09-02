/**
 * 🔴 Agent 事件总线(Redis Streams)— Phase 1 事件主干
 *
 * 目标:让 agent 执行事件(jobId 级 thought/tool/result/...)跨进程可见,
 * 取代 SSE 链路上的进程内 globalThis emitter 与 600ms Temporal 轮询。
 * TS 侧先行:engine-py(Python)上线后向同一条流发布,网关无感切换。
 *
 * 线上协议保持不变:
 * - SSE id 仍为每 job 单调递增整数序号(REDIS INCR),与既有 Last-Event-ID
 *   断线重放语义、前端 EventSource 完全兼容;
 * - 流即缓冲:XADD MAXLEN ~200(原内存最近 100 条),TTL 10 分钟
 *   (原内存 prune TTL 10 分钟)。
 *
 * Redis 不可用时所有 API 静默降级(eventBusAvailable() === false),
 * 调用方回退进程内路径,行为与 Phase 1 之前完全一致。
 */
import { redis, useRedis } from './cache';

export interface StreamAgentEvent {
  entryId: string;
  seq: number;
  type: string;
  data: unknown;
}

const STREAM_MAXLEN = 200;
const STREAM_TTL_SECONDS = 600;
const XREAD_BLOCK_MS = 15_000;

const streamKey = (jobId: string): string => `job:events:${jobId}`;
const seqKey = (jobId: string): string => `job:seq:${jobId}`;

export function eventBusAvailable(): boolean {
  return useRedis && redis !== null;
}

/** 发布一条 job 级事件;失败静默降级(进程内事件流不受影响,不阻断执行) */
export async function publishAgentEvent(jobId: string, type: string, data: unknown): Promise<void> {
  if (!eventBusAvailable() || !redis) return;
  try {
    const seq = await redis.incr(seqKey(jobId));
    await redis.xadd(
      streamKey(jobId),
      'MAXLEN',
      '~',
      STREAM_MAXLEN,
      '*',
      'seq',
      String(seq),
      'type',
      type,
      'data',
      JSON.stringify(data ?? null),
    );
    await redis.expire(streamKey(jobId), STREAM_TTL_SECONDS);
    await redis.expire(seqKey(jobId), STREAM_TTL_SECONDS);
  } catch {
    // 静默降级:跨进程总线不可用时,进程内事件流仍然完整
  }
}

function parseEntry(entryId: string, fields: string[]): StreamAgentEvent | null {
  const map: Record<string, string> = {};
  for (let i = 0; i + 1 < fields.length; i += 2) {
    map[fields[i]] = fields[i + 1];
  }
  const seq = Number.parseInt(map.seq ?? '', 10);
  if (!map.type || Number.isNaN(seq)) return null;
  let data: unknown = null;
  try {
    data = map.data ? JSON.parse(map.data) : null;
  } catch {
    data = map.data ?? null;
  }
  return { entryId, seq, type: map.type, data };
}

/**
 * 读取一个 job 的全部事件(≤ MAXLEN 条),按 seq 升序。
 * 调用方自行按 seq > lastEventId 过滤重放窗口,并取末条 entryId 作续读游标。
 */
export async function readAgentEvents(jobId: string): Promise<StreamAgentEvent[]> {
  if (!eventBusAvailable() || !redis) return [];
  try {
    const res = await redis.xrange(streamKey(jobId), '-', '+');
    if (!res) return [];
    return res
      .map(([entryId, fields]) => parseEntry(entryId, fields))
      .filter((e): e is StreamAgentEvent => e !== null)
      .sort((a, b) => a.seq - b.seq);
  } catch {
    return [];
  }
}

export interface WatchOptions {
  /** 每轮 XREAD 阻塞时长(ms),与 SSE 心跳周期对齐 */
  blockMs?: number;
  /** 返回 true 时停止消费 */
  shouldStop: () => boolean;
}

/**
 * 从 fromEntryId(不含)起持续消费事件,逐批回调;阻塞式循环,
 * 直到 shouldStop() 为真或 Redis 异常(调用方 cleanup,客户端带 Last-Event-ID 重连自愈)。
 */
export async function watchAgentEvents(
  jobId: string,
  fromEntryId: string,
  onBatch: (events: StreamAgentEvent[]) => void,
  options: WatchOptions,
): Promise<void> {
  if (!eventBusAvailable() || !redis) return;
  const blockMs = options.blockMs ?? XREAD_BLOCK_MS;
  let cursor = fromEntryId;
  while (!options.shouldStop()) {
    try {
      const res = await redis.xread('BLOCK', blockMs, 'COUNT', 50, 'STREAMS', streamKey(jobId), cursor);
      if (!res || res.length === 0) continue;
      const [, entries] = res[0];
      const batch: StreamAgentEvent[] = [];
      for (const [entryId, fields] of entries) {
        const parsed = parseEntry(entryId, fields);
        if (parsed) {
          batch.push(parsed);
          cursor = entryId;
        }
      }
      if (batch.length > 0) onBatch(batch);
    } catch {
      return; // 总线异常:交还调用方 cleanup,重连后从 Last-Event-ID 续读
    }
  }
}
