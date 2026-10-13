// @vitest-environment node
// 商店聊天 SSE 连接机契约:P7 指数退避重建(aaa2aba 风暴收口)+ ADR-0013①
// 重连补投前端半边(message 帧 id: 行记水位,重建时 lastEventId query 带回)。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildStoreStreamUrl, openStoreStream } from './storeStreamConnection';

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static reset() {
    FakeEventSource.instances = [];
  }
  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  private listeners = new Map<string, ((e: unknown) => void)[]>();
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: unknown) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), cb]);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, e: unknown) {
    for (const cb of this.listeners.get(type) ?? []) cb(e);
  }
}

describe('buildStoreStreamUrl', () => {
  it('首连(无水位)不带 lastEventId 参数 —— 首连不重放契约', () => {
    const url = buildStoreStreamUrl('thread_1', 'aurora', null);
    expect(url).toBe('/api/store/chat/stream?threadId=thread_1&businessId=aurora');
    expect(url).not.toContain('lastEventId');
  });

  it('带水位时以 lastEventId query 回传(chat.py 同名契约)', () => {
    expect(buildStoreStreamUrl('thread_1', 'aurora', '1730000000000')).toBe(
      '/api/store/chat/stream?threadId=thread_1&businessId=aurora&lastEventId=1730000000000',
    );
  });

  it('threadId/businessId 走 encodeURIComponent', () => {
    const url = buildStoreStreamUrl('a&b', 'aurora', null);
    expect(url).toContain('threadId=a%26b');
  });
});

describe('openStoreStream', () => {
  beforeEach(() => {
    FakeEventSource.reset();
    vi.useFakeTimers();
    (globalThis as { EventSource?: unknown }).EventSource = FakeEventSource;
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    (globalThis as { EventSource?: unknown }).EventSource = undefined;
  });

  const lastOf = () => FakeEventSource.instances[FakeEventSource.instances.length - 1];

  it('message 帧的 lastEventId 被记为水位,退避重建时带回 URL', () => {
    const messages: string[] = [];
    openStoreStream({ threadId: 't1', businessId: 'aurora', onMessage: (raw) => messages.push(raw) });
    const first = lastOf();
    first.emit('message', { data: '{"content":"hi"}', lastEventId: '1730000000001' });
    first.onerror?.();

    // 退避 1s 后重建,URL 带回水位
    vi.advanceTimersByTime(1000);
    expect(lastOf()).not.toBe(first);
    expect(lastOf().url).toContain('lastEventId=1730000000001');
    expect(messages).toEqual(['{"content":"hi"}']);
  });

  it('无 id: 行的帧(connected/心跳形)不污染水位', () => {
    openStoreStream({ threadId: 't1', businessId: 'aurora', onMessage: () => {} });
    const first = lastOf();
    first.emit('message', { data: '{"threadId":"t1"}', lastEventId: '' });
    first.emit('message', { data: '{"content":"x"}', lastEventId: '1730000000002' });
    first.onerror?.();
    vi.advanceTimersByTime(1000);
    expect(lastOf().url).toContain('lastEventId=1730000000002');
  });

  it('指数退避 1s→2s,onopen 重置;超 MAX_RETRY 停止重建', () => {
    openStoreStream({ threadId: 't1', businessId: 'aurora', onMessage: () => {}, maxRetry: 2 });
    // 第 1 断:1s 后重建(第 2 连)
    lastOf().onerror?.();
    vi.advanceTimersByTime(999);
    expect(FakeEventSource.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeEventSource.instances).toHaveLength(2);
    // 第 2 断:2s 后重建(第 3 连)
    lastOf().onerror?.();
    vi.advanceTimersByTime(1999);
    expect(FakeEventSource.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeEventSource.instances).toHaveLength(3);
    // 第 3 断:已达 MAX_RETRY=2,不再重建
    lastOf().onerror?.();
    vi.advanceTimersByTime(60_000);
    expect(FakeEventSource.instances).toHaveLength(3);
    // 出错即 close,P7 语义:浏览器自动重连被禁用
    expect(FakeEventSource.instances.every((es) => es.closed)).toBe(true);
  });

  it('onopen 重置退避计数:连续稳定后重连延迟从 1s 重新起步', () => {
    openStoreStream({ threadId: 't1', businessId: 'aurora', onMessage: () => {} });
    // 断→1s→重建→open 重置→断:仍应 1s(而非 2s)后重建
    lastOf().onerror?.();
    vi.advanceTimersByTime(1000);
    lastOf().onopen?.();
    lastOf().onerror?.();
    vi.advanceTimersByTime(999);
    const countAfter999ms = FakeEventSource.instances.length;
    vi.advanceTimersByTime(1);
    expect(countAfter999ms).toBe(2);
    expect(FakeEventSource.instances).toHaveLength(3);
  });

  it('close() 后不再重建(组件卸载语义)', () => {
    const handle = openStoreStream({ threadId: 't1', businessId: 'aurora', onMessage: () => {} });
    handle.close();
    lastOf().onerror?.();
    vi.advanceTimersByTime(60_000);
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(lastOf().closed).toBe(true);
  });

  it('补投闭环:重连后的重放帧推进水位,再断线时带回新水位', () => {
    openStoreStream({ threadId: 't1', businessId: 'aurora', onMessage: () => {} });
    // 第一断:水位 w1
    lastOf().emit('message', { data: '{"content":"live"}', lastEventId: '1730000000001' });
    lastOf().onerror?.();
    vi.advanceTimersByTime(1000);
    // 重连后服务端重放断线窗口帧(带 id)—— 水位必须随之前移
    const reconnected = lastOf();
    expect(reconnected.url).toContain('lastEventId=1730000000001');
    reconnected.emit('message', { data: '{"content":"replayed"}', lastEventId: '1730000000050' });
    reconnected.onerror?.();
    vi.advanceTimersByTime(2000);
    // 第二次重建带回的是重放帧的水位,不是第一次的
    expect(lastOf().url.endsWith('lastEventId=1730000000050')).toBe(true);
  });
});
