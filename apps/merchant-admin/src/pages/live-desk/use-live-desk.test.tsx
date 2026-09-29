// P4 前端逻辑专测(spec §2.6/§2.7):clientMsgId 幂等发送(乐观气泡 + ack 失败
// 回真源不盲删)、台内批驳错误透传(403/400 detail 如实呈现)、typing 收发
// (对端过滤 + 2.5s 保持窗 + 上行 1.5s 节流)。socket.io-client 与 api 层全
// mock,不依赖运行中的网关。
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useLiveDesk } from './use-live-desk';

const mocks = vi.hoisted(() => {
  const emit = vi.fn();
  return {
    emit,
    socket: { connected: true, on: vi.fn(), emit, close: vi.fn() },
    conversations: vi.fn(),
    presence: vi.fn(),
    context: vi.fn(),
    timeline: vi.fn(),
    pendingApprovals: vi.fn(),
    resolveApproval: vi.fn(),
    setDnd: vi.fn(),
    noteCreate: vi.fn(),
    noteDelete: vi.fn(),
  };
});

vi.mock('socket.io-client', () => ({ io: vi.fn(() => mocks.socket) }));

vi.mock('@/lib/api', () => ({
  api: {
    liveDesk: {
      conversations: mocks.conversations,
      presence: mocks.presence,
      context: mocks.context,
      timeline: mocks.timeline,
      pendingApprovals: mocks.pendingApprovals,
      resolveApproval: mocks.resolveApproval,
      setDnd: mocks.setDnd,
      noteCreate: mocks.noteCreate,
      noteDelete: mocks.noteDelete,
    },
  },
  authToken: () => 'jwt-token',
  currentStaffEmail: () => 'agent@aurora',
}));

const handlers = new Map<string, (p: unknown) => void>();

beforeEach(() => {
  vi.clearAllMocks();
  handlers.clear();
  mocks.socket.on.mockImplementation((event: string, fn: (p: unknown) => void) => {
    handlers.set(event, fn);
  });
  mocks.conversations.mockResolvedValue({ success: true, conversations: [] });
  mocks.presence.mockResolvedValue({ success: true, agents: [] });
  mocks.context.mockResolvedValue({ success: true });
  mocks.timeline.mockResolvedValue({ success: true, data: { messages: [] } });
  mocks.pendingApprovals.mockResolvedValue({ success: true, approvals: [] });
});

async function renderDesk() {
  const utils = renderHook(() => useLiveDesk());
  await act(async () => {}); // flush 初始 effects(socket 建连 + 首载)
  return utils;
}

describe('sendMessage 幂等发送(P4 §2.7)', () => {
  it('乐观气泡先行,ack 成功后整表对齐真源,并透传 clientMsgId', async () => {
    const { result } = await renderDesk();
    mocks.timeline.mockResolvedValue({
      success: true,
      data: { messages: [{ id: 'u1', role: 'user', content: '你好' }] },
    });
    await act(async () => {
      await result.current.openThread('t1');
    });
    expect(result.current.timeline).toHaveLength(1);

    let sentPayload: Record<string, unknown> = {};
    mocks.emit.mockImplementation((event: string, payload: Record<string, unknown>, ack?: (a: unknown) => void) => {
      if (event === 'send_message') {
        sentPayload = payload;
        ack?.({ success: true, messageId: 'srv-known' });
      }
    });
    // 服务端以 clientMsgId 落库;这里返回不同 id 以证明发生的是整表重同步
    mocks.timeline.mockResolvedValue({
      success: true,
      data: {
        messages: [
          { id: 'u1', role: 'user', content: '你好' },
          { id: 'srv-known', role: 'operator', content: '在的' },
        ],
      },
    });

    await act(async () => {
      await result.current.sendMessage('t1', '在的');
    });

    expect(String(sentPayload.clientMsgId)).toMatch(/^[0-9a-zA-Z-]{8,64}$/);
    expect(sentPayload.content).toBe('在的');
    expect(result.current.timeline.map((m) => m.id)).toEqual(['u1', 'srv-known']);
    // openThread 一次 + 发送后对齐一次
    expect(mocks.timeline).toHaveBeenCalledTimes(2);
  });

  it('ack 失败也回真源:已落库的消息如实显示,不盲删', async () => {
    const { result } = await renderDesk();
    mocks.emit.mockImplementation((event: string, _p: unknown, ack?: (a: unknown) => void) => {
      if (event === 'send_message') ack?.({ success: false, error: '响应超时,请重试' });
    });
    mocks.timeline.mockResolvedValue({
      success: true,
      data: { messages: [{ id: 'u1', role: 'user', content: 'hi' }] },
    });
    await act(async () => {
      await result.current.openThread('t1');
    });
    // 落库而 ack 未达:重拉真源应含该消息
    mocks.timeline.mockResolvedValue({
      success: true,
      data: {
        messages: [
          { id: 'u1', role: 'user', content: 'hi' },
          { id: 'kept', role: 'operator', content: '在的' },
        ],
      },
    });
    const ack = await act(() => result.current.sendMessage('t1', '在的'));
    expect(ack.success).toBe(false);
    expect(result.current.timeline.map((m) => m.id)).toEqual(['u1', 'kept']);
  });

  it('ack 失败且未落库:乐观气泡消失(回滚)', async () => {
    const { result } = await renderDesk();
    mocks.emit.mockImplementation((event: string, _p: unknown, ack?: (a: unknown) => void) => {
      if (event === 'send_message') ack?.({ success: false, error: '发送失败' });
    });
    mocks.timeline.mockResolvedValue({
      success: true,
      data: { messages: [{ id: 'u1', role: 'user', content: 'hi' }] },
    });
    await act(async () => {
      await result.current.openThread('t1');
    });
    await act(async () => {
      await result.current.sendMessage('t1', '没发出去');
    });
    expect(result.current.timeline.map((m) => m.id)).toEqual(['u1']);
  });
});

describe('openThread 同会话重入(2026-09-29 防抖动)', () => {
  it('new_message 回环重入不塌空时间线(塌空即「发消息抖一下」),换会话仍清防串栏', async () => {
    const { result } = await renderDesk();
    mocks.timeline.mockResolvedValue({
      success: true,
      data: { messages: [{ id: 'u1', role: 'user', content: 'hi' }] },
    });
    await act(async () => {
      await result.current.openThread('t1');
    });
    expect(result.current.timeline).toHaveLength(1);
    // 同会话重入(服务端 new_message 房间回环/发送后对齐真源):拉取在途时
    // 时间线保持不闪空 —— 旧实现先 setTimeline([]) 再重灌,中间帧塌 0 即抖动。
    // 挂起拉取才能观测到旧实现的中间塌空帧(终态两边相同,终态断言钉不住)。
    mocks.timeline.mockImplementation(() => new Promise(() => {}));
    await act(async () => {
      void result.current.openThread('t1');
    });
    expect(result.current.timeline).toHaveLength(1);
    // 换会话:同步清旧时间线防串栏(拉取失败也不残留上一会话的消息)
    mocks.timeline.mockRejectedValue(new Error('断网'));
    await act(async () => {
      await result.current.openThread('t2');
    });
    expect(result.current.timeline).toHaveLength(0);
  });

  it('join_thread 每会话只发一次(重入不再重复入房)', async () => {
    const { result } = await renderDesk();
    await act(async () => {
      await result.current.openThread('t1');
    });
    await act(async () => {
      await result.current.openThread('t1');
    });
    await act(async () => {
      await result.current.openThread('t2');
    });
    const joins = mocks.emit.mock.calls.filter(([e]) => e === 'join_thread');
    expect(joins.map(([, p]) => (p as { threadId: string }).threadId)).toEqual(['t1', 't2']);
  });
});

describe('reviewTicket 台内批驳(P4 §2.6)', () => {
  it('403/400 的服务端 detail 如实透传,不吞进通用文案', async () => {
    const { result } = await renderDesk();
    mocks.resolveApproval.mockResolvedValue({ success: false, detail: '无工单批驳权限(live_desk:approve)' });
    const r = await act(() => result.current.reviewTicket('ap1', 'reject', '证据不足'));
    expect(r).toEqual({ success: false, error: '无工单批驳权限(live_desk:approve)' });
    expect(mocks.resolveApproval).toHaveBeenCalledWith({
      approvalId: 'ap1',
      action: 'reject',
      rejectionReason: '证据不足',
    });
  });

  it('网络异常落 err.message', async () => {
    const { result } = await renderDesk();
    mocks.resolveApproval.mockRejectedValue(new Error('网络请求失败'));
    const r = await act(() => result.current.reviewTicket('ap1', 'approve'));
    expect(r).toEqual({ success: false, error: '网络请求失败' });
  });

  it('成功后刷新待批卡与会话列表,不自动释放', async () => {
    const { result } = await renderDesk();
    await act(async () => {
      await result.current.openThread('t1');
    });
    const callsBefore = mocks.pendingApprovals.mock.calls.length;
    mocks.resolveApproval.mockResolvedValue({ success: true, status: 'rejected' });
    const r = await act(() => result.current.reviewTicket('ap1', 'reject', '证据不足'));
    expect(r).toEqual({ success: true });
    expect(mocks.pendingApprovals.mock.calls.length).toBeGreaterThan(callsBefore);
    expect(mocks.conversations).toHaveBeenCalled();
    // 批驳 ≠ 释放:不得发出 release_takeover
    expect(mocks.emit.mock.calls.some(([e]) => e === 'release_takeover')).toBe(false);
  });
});

describe('typing 输入态(P4)', () => {
  it('顾客输入点亮「对方正在输入」,同事坐席与他人会话忽略,2.5s 保持窗后熄灭', async () => {
    vi.useFakeTimers();
    try {
      const { result } = await renderDesk();
      await act(async () => {
        await result.current.openThread('t1');
      });
      const onTyping = handlers.get('user_typing');
      expect(onTyping).toBeTypeOf('function');
      act(() => onTyping?.({ threadId: 't1', role: 'user' }));
      expect(result.current.peerTyping).toBe(true);
      act(() => onTyping?.({ threadId: 't1', role: 'operator' })); // 同事坐席不显示
      act(() => onTyping?.({ threadId: 'other', role: 'user' })); // 非选中会话不显示
      expect(result.current.peerTyping).toBe(true);
      act(() => vi.advanceTimersByTime(2_500));
      expect(result.current.peerTyping).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('emitTyping 上行 1.5s 节流:窗口内重复输入只 emit 一次', async () => {
    vi.useFakeTimers();
    try {
      const { result } = await renderDesk();
      const typingCalls = () => mocks.emit.mock.calls.filter(([e]) => e === 'typing');
      act(() => result.current.emitTyping('t1'));
      act(() => result.current.emitTyping('t1'));
      act(() => result.current.emitTyping('t1'));
      expect(typingCalls()).toHaveLength(1);
      act(() => vi.advanceTimersByTime(1_500));
      act(() => result.current.emitTyping('t1'));
      expect(typingCalls()).toHaveLength(2);
      expect(typingCalls()[0]?.[1]).toMatchObject({ threadId: 't1', tenantId: 'aurora', role: 'operator' });
    } finally {
      vi.useRealTimers();
    }
  });
});
