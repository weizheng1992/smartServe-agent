import { render } from '@testing-library/react';
import { act } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useWorkbenchState } from './workbench';

// 审批原因直传契约钉(2026-10-15 快修):handleApprovalAction(id, 'reject', reason)
// 必须把用户填写的原因放进 POST body —— 此前审批抽屉 onReject 先写
// setRejectionReasons 再调用,stale closure 使原因被吞成机器兜底文案
// (工单 04 同病灶;RejectDialog 已修直传,抽屉接线这次收口)。
// workbench 的 fetcher = authedFetch(@/lib/api),桩在此截获 POST body。
//
// 候选⑤补钉(2026-10-15):旧面发送不变量此前零覆盖(use-live-desk.test 只钉新面)
// —— ①fallback clientMsgId 必须满足服务端正则 ^[0-9a-zA-Z-]{8,64}$(
//    realtime.py:34;旧实现下划线分隔被服务端剥成空串换发 uuid,幂等键丢失);
// ②拨号 8s 超时不再毒化模块单例(清 deskSocketPromise + 关 socket),
//    超时后下一次发送重新拨号可成功。

const mocks = vi.hoisted(() => ({
  authedFetch: vi.fn(),
  ordersList: vi.fn(),
  approvalsList: vi.fn(),
  convsList: vi.fn(),
  convsMessages: vi.fn(),
}));

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    authedFetch: mocks.authedFetch,
    api: {
      ...actual.api,
      orders: { ...actual.api.orders, list: mocks.ordersList },
      approvals: { ...actual.api.approvals, list: mocks.approvalsList },
      conversations: {
        ...actual.api.conversations,
        list: mocks.convsList,
        messages: mocks.convsMessages,
      },
    },
  };
});

// socket.io 假件:捕获 io 实例与 emit 载荷;ack 以微任务异步回(success:true)
const socketMocks = vi.hoisted(() => {
  const instances: any[] = [];
  function makeFakeSocket() {
    const handlers = new Map<string, Array<() => void>>();
    const emits: Array<{ event: string; payload: Record<string, unknown>; ack?: (r: unknown) => void }> = [];
    const sock = {
      connected: false,
      close: vi.fn(),
      on: vi.fn((ev: string, cb: () => void) => {
        handlers.set(ev, [...(handlers.get(ev) || []), cb]);
      }),
      emit: vi.fn((ev: string, payload: Record<string, unknown>, ack?: (r: unknown) => void) => {
        emits.push({ event: ev, payload, ack });
        if (ack) queueMicrotask(() => ack({ success: true, messageId: 'srv-m1' }));
      }),
      __connect: () => {
        sock.connected = true;
        handlers.get('connect')?.forEach((cb) => cb());
      },
      __emits: emits,
    };
    instances.push(sock);
    return sock;
  }
  return { instances, makeFakeSocket, io: vi.fn(() => makeFakeSocket()) };
});

vi.mock('socket.io-client', () => ({ io: socketMocks.io }));

const emptyOk = { ok: true, json: async () => ({ success: true }) };
const ONE_CONV = {
  success: true,
  conversations: [{ id: 't-1', threadId: 't-1', businessId: 'aurora', status: 'ai', lastMessage: 'hi' }],
};
mocks.ordersList.mockResolvedValue({ success: true, orders: [], auditLogs: [] });
mocks.approvalsList.mockResolvedValue({ success: true, approvals: [] });
mocks.convsList.mockResolvedValue(ONE_CONV);
mocks.convsMessages.mockResolvedValue({ success: true, data: { messages: [] } });

function Harness({ onReady }: { onReady: (w: ReturnType<typeof useWorkbenchState>) => void }) {
  const w = useWorkbenchState('approvals');
  onReady(w);
  return null;
}

async function mountWithActiveThread(onReady: (w: ReturnType<typeof useWorkbenchState>) => void) {
  const spy = vi.fn(onReady);
  render(<Harness onReady={spy} />);
  await vi.waitFor(() => expect(mocks.convsList).toHaveBeenCalled());
  // 自动选中首个会话(activeThreadId 就位)后才可发送
  await vi.waitFor(() =>
    expect(spy.mock.calls.some(([w]) => (w as { activeThreadId?: string }).activeThreadId === 't-1')).toBe(true),
  );
}

describe('workbench 审批动作(驳回原因契约)', () => {
  it('handleApprovalAction 直传 explicitReason:用户填写的原因原样进 POST body', async () => {
    let w!: ReturnType<typeof useWorkbenchState>;
    render(<Harness onReady={(x) => (w = x)} />);
    await vi.waitFor(() => expect(mocks.ordersList).toHaveBeenCalled());

    mocks.authedFetch.mockResolvedValue(emptyOk);
    await act(async () => {
      await w.handleApprovalAction('a1', 'reject', '用户填写的原因');
    });

    const call = mocks.authedFetch.mock.calls.find(([u]) => String(u).includes('/api/admin/approvals'));
    expect(call).toBeDefined();
    expect(JSON.parse(String(call![1].body))).toMatchObject({
      approvalId: 'a1',
      action: 'reject',
      rejectionReason: '用户填写的原因',
    });
  });

  it('未填原因:机器兜底文案仍在(不空串)', async () => {
    let w!: ReturnType<typeof useWorkbenchState>;
    render(<Harness onReady={(x) => (w = x)} />);
    await vi.waitFor(() => expect(mocks.ordersList).toHaveBeenCalled());

    mocks.authedFetch.mockResolvedValue(emptyOk);
    await act(async () => {
      await w.handleApprovalAction('a2', 'reject');
    });

    const call = mocks.authedFetch.mock.calls.filter(([u]) => String(u).includes('/api/admin/approvals')).at(-1);
    expect(JSON.parse(String(call![1].body))).toMatchObject({
      approvalId: 'a2',
      action: 'reject',
      rejectionReason: '退款申请不符合政策要求。',
    });
  });
});

describe('workbench 坐席发送(旧面不变量,候选⑤补钉)', () => {
  // 顺序即隔离:毒化用例消费文件初始的干净单例,fallback 用例复用其换签后的缓存 socket
  // (vi.resetModules 会复制 React 两份,跨拷贝 act 互不认领 —— 不走模块重置)
  it('拨号 8s 超时不再毒化单例:超时后下一次发送重新拨号可成功', async () => {
    vi.useFakeTimers();
    try {
      let fw!: ReturnType<typeof useWorkbenchState>;
      act(() => {
        render(<Harness onReady={(x) => (fw = x)} />);
      });
      // 挂载拉取 + 首线程自选(纯微任务,advance(0) 冲一次即可)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(fw.activeThreadId).toBe('t-1');

      // 第一次发送:假 socket 永不 connect → 8s 拨号超时
      await act(async () => {
        void fw.handleSendMessage('第一条');
        await vi.advanceTimersByTimeAsync(8_000);
      });
      const first = socketMocks.instances[0];
      expect(first.close).toHaveBeenCalled(); // 修复:孤儿 socket 不再泄漏

      // 第二次发送:重新拨号,连上即成功(修复前:永远 await 已 reject 的旧 promise)
      let secondDone = false;
      await act(async () => {
        void fw.handleSendMessage('第二条').then(() => {
          secondDone = true;
        });
      });
      expect(socketMocks.instances.length).toBe(2);
      const second = socketMocks.instances.at(-1)!;
      act(() => {
        second.__connect();
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(secondDone).toBe(true);
      const sends = second.__emits.filter((e: { event: string }) => e.event === 'send_message');
      expect(sends).toHaveLength(1);
      expect(sends[0].payload.content).toBe('第二条');
    } finally {
      vi.useRealTimers();
    }
  });

  it('fallback clientMsgId(不可用 randomUUID)满足服务端正则 ^[0-9a-zA-Z-]{8,64}$', async () => {
    let w!: ReturnType<typeof useWorkbenchState>;
    render(<Harness onReady={(x) => (w = x)} />);
    await mountWithActiveThread((x) => (w = x));

    // 模拟非安全源/老 webview:randomUUID 不可用 → 走 fallback 分支
    const original = (globalThis.crypto as { randomUUID?: () => string }).randomUUID;
    Object.defineProperty(globalThis.crypto, 'randomUUID', { value: undefined, configurable: true });
    try {
      await act(async () => {
        await w.handleSendMessage('你好');
      });
    } finally {
      Object.defineProperty(globalThis.crypto, 'randomUUID', { value: original, configurable: true });
    }

    const sock = socketMocks.instances.at(-1)!;
    const send = sock.__emits.find((e: { event: string }) => e.event === 'send_message');
    expect(send).toBeDefined();
    // 旧实现 `opt_${Date.now()}_${…}`(下划线)被服务端正则剥成空串换发 uuid,幂等键丢失
    expect(String(send!.payload.clientMsgId)).toMatch(/^[0-9a-zA-Z-]{8,64}$/);
    expect(String(send!.payload.clientMsgId)).toSatisfy((s: string) => !s.includes('_'));
  });
});
