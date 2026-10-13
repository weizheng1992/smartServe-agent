// 商店聊天 SSE 连接机 —— FloatingChatWidget 实时流的建立/断线/重建全生命周期。
//
// 两段历史在此汇合:
// - P7(aaa2aba,2026-10-03):EventSource 对 4xx(属主闸 403/线程 404)也会
//   自动重连,重连必然同结果 = 无限重连风暴打在服务端租户闸上 → onerror 即
//   close 浏览器自动重连,改显式指数退避重建(1s→2s→上限 30s,open 重置,
//   连败上限后停止,等 effect 重跑自然重建)。
// - ADR-0013① 收口(2026-10-13):P7 的重建是新建 EventSource,无法携带
//   Last-Event-ID header,服务端重放闸因此恒假,断线窗口消息仍丢 → message
//   帧的 ``id:`` 行(服务端 frame_id_from_timestamp 发射)记为水位,重建时
//   以 lastEventId query 带回(query 契约与 chat.py 同名,服务端
//   last_event_id_from 的 query_fallback 路径)。重叠帧由消费方按消息 id
//   幂等吸收,首连(无水位)不重放。

/** stream URL 构造:水位存在时以 lastEventId query 带回,首连不带(不重放)。 */
export function buildStoreStreamUrl(threadId: string, businessId: string, lastEventId: string | null): string {
  const base = `/api/store/chat/stream?threadId=${encodeURIComponent(threadId)}&businessId=${encodeURIComponent(businessId)}`;
  return lastEventId ? `${base}&lastEventId=${encodeURIComponent(lastEventId)}` : base;
}

export interface StoreStreamHandle {
  close: () => void;
}

const DEFAULT_MAX_RETRY = 6;

export function openStoreStream(params: {
  threadId: string;
  businessId: string;
  /** 原始 message 帧 data(JSON 串),解析与消费归调用方。 */
  onMessage: (rawData: string) => void;
  maxRetry?: number;
}): StoreStreamHandle {
  const maxRetry = params.maxRetry ?? DEFAULT_MAX_RETRY;
  let eventSource: EventSource | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let retryCount = 0;
  let disposed = false;
  let lastEventId: string | null = null;

  const connect = () => {
    if (disposed) return;
    try {
      eventSource = new EventSource(buildStoreStreamUrl(params.threadId, params.businessId, lastEventId));

      eventSource.onopen = () => {
        retryCount = 0;
      };

      eventSource.addEventListener('message', (e) => {
        const frame = e as MessageEvent<string>;
        // 帧 id 即水位:服务端对 message 帧补 id: 行(timestamp → epoch ms),
        // 无 id 形状(connected/心跳/容灾回落)不得清掉已记水位
        if (frame.lastEventId) lastEventId = frame.lastEventId;
        params.onMessage(frame.data);
      });

      eventSource.onerror = () => {
        // P7:close 掉浏览器自动重连,显式指数退避后重建(避免 4xx 无限风暴);
        // 重建经 buildStoreStreamUrl 带回水位(ADR-0013① 收口)
        eventSource?.close();
        if (disposed || retryCount >= maxRetry) return;
        const delay = Math.min(1000 * 2 ** retryCount, 30_000);
        retryCount += 1;
        retryTimer = setTimeout(connect, delay);
      };
    } catch (err) {
      console.warn('[SSE] Failed to initialize EventSource:', err);
    }
  };
  connect();

  return {
    close: () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      eventSource?.close();
    },
  };
}
