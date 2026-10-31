// 通知信号流连接机(mall-notifications 05)—— 同族 storeStreamConnection.ts,
// 沿 P7 显式指数退避(1s→2s→上限 30s,open 重置,连败上限后停,等 effect 重跑
// 自然重建)。
//
// 与聊天流两处刻意不同(服务端 03 裁决,.scratch/mall-notifications):
// ①无水位回传 —— 通知流无 DB 时间线回放,断线窗口丢信号不丢数据(数据真源
//   恒为列表/未读数端点);重连成功即触发一次 onSignal 重拉自愈,首连不触发
//   (调用方挂载时本就拉一次)。
// ②帧过滤在本机做 —— 服务端单频道 fan-in 转发,定向帧携 targetUserId,
//   非本人帧在此丢弃不上抛;广播帧(无 targetUserId)人人重拉。

export interface NotifyStreamHandle {
  close: () => void;
}

const DEFAULT_MAX_RETRY = 6;

export function buildNotifyStreamUrl(userId: string, businessId: string): string {
  return `/api/store/notifications/stream?userId=${encodeURIComponent(userId)}&businessId=${encodeURIComponent(businessId)}`;
}

/** 帧过滤纯函数(连接机唯一判断逻辑,单测钉死):notification 类型 + 非本人
 *  定向帧过滤;非 JSON 帧诚实忽略(心跳/容灾形状由泵保证,防御性不炸)。 */
export function isSignalForMe(rawData: string, userId: string): boolean {
  try {
    const frame = JSON.parse(rawData) as { type?: string; targetUserId?: string };
    if (frame.type !== 'notification') return false;
    if (frame.targetUserId && frame.targetUserId !== userId) return false;
    return true;
  } catch {
    return false;
  }
}

export function openNotifyStream(params: {
  userId: string;
  businessId: string;
  /** 收到本人相关信号(或断线重连自愈)时触发;调用方据此重拉未读数。 */
  onSignal: () => void;
  maxRetry?: number;
}): NotifyStreamHandle {
  const maxRetry = params.maxRetry ?? DEFAULT_MAX_RETRY;
  let eventSource: EventSource | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let retryCount = 0;
  let disposed = false;

  const connect = () => {
    if (disposed) return;
    try {
      eventSource = new EventSource(buildNotifyStreamUrl(params.userId, params.businessId));

      eventSource.onopen = () => {
        const isReconnect = retryCount > 0;
        retryCount = 0;
        if (isReconnect) params.onSignal();
      };

      eventSource.addEventListener('message', (e) => {
        if (isSignalForMe((e as MessageEvent<string>).data, params.userId)) {
          params.onSignal();
        }
      });

      eventSource.onerror = () => {
        // P7:close 掉浏览器自动重连,显式指数退避后重建
        eventSource?.close();
        if (disposed || retryCount >= maxRetry) return;
        const delay = Math.min(1000 * 2 ** retryCount, 30_000);
        retryCount += 1;
        retryTimer = setTimeout(connect, delay);
      };
    } catch (err) {
      console.warn('[NotifySSE] Failed to initialize EventSource:', err);
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
