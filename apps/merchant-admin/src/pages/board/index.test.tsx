import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BoardPage from './index';

// Ask 会话 core 以 AskStreamError instanceof 判恢复句柄(与 FloatingAgent.test
// 同一模式):桩必须导出真类,否则 appendError 当场 TypeError、错误帧落不了
vi.mock('@/lib/api', () => {
  class AskStreamError extends Error {
    askId: string;
    lastEventId: number;
    frames: unknown[];
    constructor(message: string, askId: string, lastEventId: number, frames: unknown[] = []) {
      super(message);
      this.name = 'AskStreamError';
      this.askId = askId;
      this.lastEventId = lastEventId;
      this.frames = frames;
    }
  }
  return {
    AskStreamError,
    api: {
      ask: vi.fn(),
      // 服务额度只读卡(2026-10-21 配额闸)挂看板页:桩给最小成功体,卡内自消化
      credits: {
        get: vi.fn(async () => ({
          success: true,
          data: { businessId: 'aurora', balance: 500, transactions: [] },
        })),
      },
    },
  };
});

import { api } from '@/lib/api';
const askMock = api.ask as unknown as ReturnType<typeof vi.fn>;

const RESULT_FRAME = [
  {
    event: 'result',
    data: {
      metric: 'volume',
      unit: '件',
      caliber: '口径',
      rows: [
        { a: 1, b: 2 },
        { a: 2, b: 4 },
      ],
      cards: [
        {
          type: 'table',
          title: 't',
          columns: [
            { key: 'a', label: 'a' },
            { key: 'b', label: 'b' },
          ],
          rows: [{ a: 1, b: 2 }],
          caliber: 'c',
        },
      ],
    },
  },
];

const PINS = [{ id: 'p1', question: '品类GMV排行', route: '/analytics', pinnedAt: '2026-09-23T00:00:00Z' }];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  localStorage.setItem('merchant-admin.board', JSON.stringify(PINS));
  // 会话经 onFrame 流式入列(与真流同构);返回值只兜底不再被消费
  askMock.mockImplementation((_q: unknown, _pc: unknown, cb?: (f: unknown) => void) => {
    for (const f of RESULT_FRAME) cb?.(f);
    return Promise.resolve(RESULT_FRAME);
  });
});

afterEach(() => {
  try {
    if (document.fullscreenElement) void document.exitFullscreen();
  } catch {}
});

describe('BoardPage(常驻看板)', () => {
  it('挂载即按钉卡重放 api.ask,并渲染结果卡', async () => {
    render(
      <MemoryRouter>
        <BoardPage />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(askMock).toHaveBeenCalledWith(
        '品类GMV排行',
        expect.objectContaining({ route: '/analytics', selection: [] }),
        expect.any(Function),
      ),
    );
    expect(screen.getByText('品类GMV排行')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('排行条形图')).toBeInTheDocument());
  });

  it('移除钉卡:从存储删除且不再重放', async () => {
    render(
      <MemoryRouter>
        <BoardPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText('品类GMV排行')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '移除' }));
    expect(screen.getByText(/还没有钉卡/)).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('merchant-admin.board')!)).toEqual([]);
  });

  it('立即刷新:再次触发重放', async () => {
    render(
      <MemoryRouter>
        <BoardPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(askMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: '立即刷新' }));
    await waitFor(() => expect(askMock).toHaveBeenCalledTimes(2));
  });

  it('busy 闸:重放在途时立即刷新被跳过(慢流>60s 严禁重叠 ask,2026-10-15 收口)', async () => {
    let release!: () => void;
    askMock.mockImplementation(
      () =>
        new Promise<void>((r) => {
          release = r;
        }),
    );
    render(
      <MemoryRouter>
        <BoardPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(askMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: '立即刷新' }));
    expect(askMock).toHaveBeenCalledTimes(1); // 在途闸:跳过本轮
    release();
    await waitFor(() => expect(screen.getByText(/刷新于/)).toBeInTheDocument());
    expect(askMock).toHaveBeenCalledTimes(1); // 释放后本轮收尾,不补发
  });

  it('重放失败:显示失败信息不崩溃(诚实帧)', async () => {
    askMock.mockRejectedValue(new Error('gateway down'));
    render(
      <MemoryRouter>
        <BoardPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText(/gateway down/)).toBeInTheDocument());
  });

  it('大屏按钮存在(全屏 API 不可用时静默)', () => {
    render(
      <MemoryRouter>
        <BoardPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole('button', { name: /大屏/ })).toBeInTheDocument();
  });
});
