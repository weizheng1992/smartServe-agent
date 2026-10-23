import { render } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { type WorkbenchScope, useWorkbenchState } from './workbench';

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

function Harness({
  onReady,
  scope = 'approvals',
}: { onReady: (w: ReturnType<typeof useWorkbenchState>) => void; scope?: WorkbenchScope }) {
  const w = useWorkbenchState(scope);
  onReady(w);
  return null;
}

// scope 数据面裁剪钉(候选⑤):此前 scope-blind 三连拉 + 3s 消息轮询任意 scope
// 自启(spi-logs 审计页三端点只消费半个、/orders 自启 3s 幽灵轮询)。每钉先
// mockClear,断言「该拉的叫了、不该拉的一次都没有」。
describe('workbench scope 数据面裁剪', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.ordersList.mockClear();
    mocks.approvalsList.mockClear();
    mocks.convsList.mockClear();
    mocks.convsMessages.mockClear();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('scope=orders:只拉订单域,审批/会话零请求,3s 消息轮询不自启;8s 轮询在跑且卸载即停', async () => {
    const { unmount } = render(<Harness scope="orders" onReady={() => {}} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.ordersList).toHaveBeenCalledTimes(1);
    expect(mocks.approvalsList).not.toHaveBeenCalled();
    expect(mocks.convsList).not.toHaveBeenCalled();
    expect(mocks.convsMessages).not.toHaveBeenCalled(); // 幽灵轮询绝迹

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8_000);
    });
    expect(mocks.ordersList).toHaveBeenCalledTimes(2); // 8s 轮询在跑

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(16_000);
    });
    expect(mocks.ordersList).toHaveBeenCalledTimes(2); // 卸载即停
  });

  it('scope=spi-logs:审计页只消费 orders 的 auditLogs 半边,审批/会话/消息零请求', async () => {
    render(<Harness scope="spi-logs" onReady={() => {}} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.ordersList).toHaveBeenCalledTimes(1);
    expect(mocks.approvalsList).not.toHaveBeenCalled();
    expect(mocks.convsList).not.toHaveBeenCalled();
    expect(mocks.convsMessages).not.toHaveBeenCalled();
  });

  it('scope=live-desk:审批+会话两域拉取,首线程自选后 3s 时间线轮询就位', async () => {
    render(<Harness scope="live-desk" onReady={() => {}} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(mocks.approvalsList).toHaveBeenCalledTimes(1);
    expect(mocks.convsList).toHaveBeenCalledTimes(1);
    // 时间线拉两趟是既有行为:首线程自选一趟 + 3s 轮询 effect 挂载即跑一趟
    expect(mocks.convsMessages).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_000);
    });
    expect(mocks.convsMessages).toHaveBeenCalledTimes(3); // +3s 轮询一次
  });
});

async function mountWithActiveThread(onReady: (w: ReturnType<typeof useWorkbenchState>) => void) {
  const spy = vi.fn(onReady);
  // 发送前提是 activeThreadId 就位 —— 仅 live-desk scope 拉会话(候选⑤裁剪)
  render(<Harness scope="live-desk" onReady={spy} />);
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
    // scope=approvals 不拉订单域(候选⑤裁剪):挂载信号换审批列表
    await vi.waitFor(() => expect(mocks.approvalsList).toHaveBeenCalled());

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
    await vi.waitFor(() => expect(mocks.approvalsList).toHaveBeenCalled());

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

// 审批「进会话」URL 指路契约钉(2026-10-23 收口,当日夜评审补测):activeThreadId
// 是组件内 state,路由切换即蒸发 —— 进会话靠 ?thread= 跨实例传递;workbench 会话
// 载荷到达时 URL 参数优先选线程(在列即选/否则首行兜底),命中即 replaceState
// 抹参一次性消费,防 8s 轮询用陈旧参数反复劫持用户后续手动选择。
describe('workbench 初始选择:URL ?thread= 指路', () => {
  beforeEach(() => {
    mocks.ordersList.mockClear();
    mocks.approvalsList.mockClear();
    mocks.convsList.mockClear();
    mocks.convsMessages.mockClear();
  });
  afterEach(() => {
    window.history.replaceState(null, '', window.location.pathname);
  });

  it('参数在线程列表内:选中目标线程并一次性抹参', async () => {
    mocks.convsList.mockResolvedValue({
      success: true,
      conversations: [
        ONE_CONV.conversations[0],
        { id: 't-9', threadId: 't-9', businessId: 'aurora', status: 'queuing', lastMessage: '审批指路' },
      ],
    });
    window.history.pushState(null, '', '/live-desk?thread=t-9');
    let w!: ReturnType<typeof useWorkbenchState>;
    render(<Harness scope="live-desk" onReady={(x) => (w = x)} />);
    await vi.waitFor(() => expect(w.activeThreadId).toBe('t-9'));
    expect(window.location.search).toBe(''); // 命中即抹参(一次性消费)
    expect(mocks.convsMessages).toHaveBeenCalledWith('t-9'); // 时间线拉的是目标线程
  });

  it('参数不在列表内:回落首行,参数保留(目标线程晚到时下一轮命中才消费)', async () => {
    window.history.pushState(null, '', '/live-desk?thread=t-404');
    let w!: ReturnType<typeof useWorkbenchState>;
    render(<Harness scope="live-desk" onReady={(x) => (w = x)} />);
    await vi.waitFor(() => expect(w.activeThreadId).toBe('t-1'));
    expect(window.location.search).toBe('?thread=t-404'); // 未命中不抹参
  });

  it('无参数:首行兜底(既有行为不回归)', async () => {
    let w!: ReturnType<typeof useWorkbenchState>;
    render(<Harness scope="live-desk" onReady={(x) => (w = x)} />);
    await vi.waitFor(() => expect(w.activeThreadId).toBe('t-1'));
    expect(window.location.search).toBe('');
  });
});

describe('workbench 坐席发送(旧面不变量,候选⑤补钉)', () => {
  // 顺序即隔离:毒化用例消费文件初始的干净单例,fallback 用例复用其换签后的缓存 socket
  // (vi.resetModules 会复制 React 两份,跨拷贝 act 互不认领 —— 不走模块重置)
  it('拨号 8s 超时不再毒化单例:超时后下一次发送重新拨号可成功', async () => {
    // 顺序即隔离:本用例是发送 describe 的首用例,deskSocketPromise 单例此刻必为
    // 干净初始态(scope/approval 用例不拨号);不走 vi.resetModules —— 模块重置
    // 会复制 React 两份,跨拷贝 act 互不认领,activeThreadId 永不就位
    vi.useFakeTimers();
    try {
      let fw!: ReturnType<typeof useWorkbenchState>;
      act(() => {
        render(<Harness scope="live-desk" onReady={(x) => (fw = x)} />);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      await vi.waitFor(() => expect(fw.activeThreadId).toBe('t-1'));

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
      const sendP = act(async () => {
        await w.handleSendMessage('你好');
      });
      // 单例缓存自毒化用例的第二次拨号:复用缓存不再新拨(instances 不增),
      // 缓存 socket 已连接,emit 即 ack(否则 8s 真等待)
      await vi.waitFor(() => expect(socketMocks.instances).toHaveLength(2));
      socketMocks.instances.at(-1)!.__connect();
      await sendP;
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
