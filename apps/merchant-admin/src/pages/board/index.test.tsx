import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BoardPage from './index';

vi.mock('@/lib/api', () => ({
  api: {
    ask: vi.fn(),
  },
}));

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
  askMock.mockResolvedValue(RESULT_FRAME);
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
