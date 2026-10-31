// @vitest-environment node
// 通知信号流连接机契约(mall-notifications 05):帧过滤纯函数(类型闸 +
// targetUserId 属主过滤 + 非 JSON 诚实忽略)与退避重建(P7 同族)。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildNotifyStreamUrl, isSignalForMe, openNotifyStream } from './notifyStreamConnection';

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

describe('isSignalForMe(帧过滤纯函数)', () => {
  it('notification 帧无 targetUserId(广播)→ 人人重拉', () => {
    expect(isSignalForMe('{"type":"notification"}', 'CUST-1')).toBe(true);
  });

  it('定向帧 targetUserId=本人 → 通过;他客 → 丢弃(客户端过滤契约)', () => {
    expect(isSignalForMe('{"type":"notification","targetUserId":"CUST-1"}', 'CUST-1')).toBe(true);
    expect(isSignalForMe('{"type":"notification","targetUserId":"CUST-2"}', 'CUST-1')).toBe(false);
  });

  it('非 notification 类型与坏 JSON 诚实忽略(心跳/容灾形状不炸)', () => {
    expect(isSignalForMe('{"type":"connected"}', 'CUST-1')).toBe(false);
    expect(isSignalForMe('not-json-at-all', 'CUST-1')).toBe(false);
  });
});

describe('buildNotifyStreamUrl', () => {
  it('userId/businessId 必带且 encodeURIComponent(身份与租户上行契约)', () => {
    const url = buildNotifyStreamUrl('CUST-1', 'aurora');
    expect(url).toBe('/api/store/notifications/stream?userId=CUST-1&businessId=aurora');
  });

  it('特殊字符走转义', () => {
    expect(buildNotifyStreamUrl('u x&y', 'a+b')).toContain('userId=u%20x%26y');
    expect(buildNotifyStreamUrl('u', 'a+b')).toContain('businessId=a%2Bb');
  });
});

describe('openNotifyStream(P7 退避同族)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource);
    FakeEventSource.reset();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('首连 onopen 不触发 onSignal(挂载时调用方本就拉一次);收到本人信号触发', () => {
    const onSignal = vi.fn();
    openNotifyStream({ userId: 'CUST-1', businessId: 'aurora', onSignal });
    const es = FakeEventSource.instances[0];
    es.onopen?.();
    expect(onSignal).not.toHaveBeenCalled(); // 首连不重拉
    es.emit('message', { data: '{"type":"notification","targetUserId":"CUST-2"}' });
    expect(onSignal).not.toHaveBeenCalled(); // 他客帧过滤
    es.emit('message', { data: '{"type":"notification"}' });
    expect(onSignal).toHaveBeenCalledTimes(1);
  });

  it('断线重连成功 onopen 触发一次 onSignal(断线窗口信号丢失的自愈拉)', () => {
    const onSignal = vi.fn();
    openNotifyStream({ userId: 'CUST-1', businessId: 'aurora', onSignal });
    const first = FakeEventSource.instances[0];
    first.onopen?.(); // 首连
    first.onerror?.(); // 掉线 → 退避
    vi.advanceTimersByTime(1000);
    const second = FakeEventSource.instances[1];
    expect(second).toBeTruthy();
    second.onopen?.();
    expect(onSignal).toHaveBeenCalledTimes(1); // 重连自愈
  });

  it('连败达上限后停止重建(4xx 风暴收口同族);close 后不再活动', () => {
    const onSignal = vi.fn();
    const handle = openNotifyStream({ userId: 'CUST-1', businessId: 'aurora', onSignal, maxRetry: 2 });
    for (let i = 0; i < 5; i += 1) {
      FakeEventSource.instances[i]?.onerror?.();
      vi.advanceTimersByTime(60_000);
    }
    expect(FakeEventSource.instances.length).toBeLessThanOrEqual(3); // 首连 + 2 次重试
    handle.close();
    FakeEventSource.instances[FakeEventSource.instances.length - 1].onerror?.();
    vi.advanceTimersByTime(60_000);
    expect(FakeEventSource.instances.length).toBeLessThanOrEqual(3); // close 后零重建
  });
});
