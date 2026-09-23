import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { FloatingAgent } from './FloatingAgent';
import * as pageContext from '@/lib/page-context';

// 纯单测:api 全桩,不碰真实网关
vi.mock('@/lib/api', () => ({
  api: {
    ask: vi.fn(),
    reports: { saveFromResult: vi.fn(), create: vi.fn() },
  },
}));

import { api } from '@/lib/api';
const askMock = api.ask as unknown as ReturnType<typeof vi.fn>;

function renderAgent(route = '/analytics') {
  return render(
    <MemoryRouter>
      <FloatingAgent route={route} />
    </MemoryRouter>,
  );
}

function openPanel() {
  fireEvent.click(screen.getByLabelText('打开数据分析助手'));
}

async function submit(q: string) {
  const input = screen.getByPlaceholderText('提问…') as HTMLInputElement;
  fireEvent.change(input, { target: { value: q } });
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  pageContext.clearSelection();
  askMock.mockResolvedValue([
    { event: 'result', data: { metric: 'volume', unit: '件', caliber: '口径A', rows: [{ a: 1 }], cards: [{ type: 'text', text: 'ok' }] } },
  ]);
});

describe('FloatingAgent(对话面板交互)', () => {
  it('发送后用户气泡即时上屏 + 思考占位(api 未返回时)', () => {
    let resolve!: (v: unknown) => void;
    askMock.mockReturnValue(new Promise((r) => { resolve = r; }));
    renderAgent();
    openPanel();
    submit('品类GMV排行');
    expect(screen.getByText('品类GMV排行')).toBeInTheDocument();
    // pending 帧与底部 busy 提示各一份,以 ≥1 断言存在性
    expect(screen.getAllByText(/正在解析问题并查询/).length).toBeGreaterThanOrEqual(1);
    resolve([]);
  });

  it('api 返回后占位被结果替换', async () => {
    renderAgent();
    openPanel();
    submit('品类GMV排行');
    await waitFor(() => expect(screen.getByText('ok')).toBeInTheDocument());
    expect(screen.queryByText(/正在解析/)).not.toBeInTheDocument();
  });

  it('api 失败:占位被错误帧替换(不悬挂)', async () => {
    askMock.mockRejectedValue(new Error('boom'));
    renderAgent();
    openPanel();
    submit('会话量多少');
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument());
    expect(screen.queryByText(/正在解析/)).not.toBeInTheDocument();
  });

  it('历史持久化:渲染时恢复 localStorage 中的帧', () => {
    localStorage.setItem('merchant-admin.agent.history', JSON.stringify([
      { id: 1, event: 'user', data: { message: '昨天的提问' } },
    ]));
    renderAgent();
    openPanel();
    expect(screen.getByText('昨天的提问')).toBeInTheDocument();
  });

  it('新对话:清空面板与历史,并轮转 sessionId', async () => {
    localStorage.setItem('merchant-admin.session', 's-old');
    localStorage.setItem('merchant-admin.agent.history', JSON.stringify([
      { id: 1, event: 'user', data: { message: '旧对话' } },
    ]));
    renderAgent();
    openPanel();
    expect(screen.getByText('旧对话')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /新对话/ }));
    expect(screen.queryByText('旧对话')).not.toBeInTheDocument();
    expect(localStorage.getItem('merchant-admin.agent.history')).toBe('[]');
    expect(localStorage.getItem('merchant-admin.session')).not.toBe('s-old');
  });

  it('勾选实时显示:选中商品后面板横幅出现且可一键清', async () => {
    renderAgent();
    openPanel();
    pageContext.setSelectionKind('spu', ['SPU-1'], { 'SPU-1': '冲锋衣' });
    const chip = await screen.findByText(/已勾选 商品 1/);
    expect(chip).toBeInTheDocument();
    fireEvent.click(chip);
    await waitFor(() => expect(screen.queryByText(/已勾选/)).not.toBeInTheDocument());
  });

  it('上行载荷:问句 + 类型化勾选 + 标签 + sessionId 一起进 api.ask', async () => {
    localStorage.setItem('merchant-admin.session', 's-test');
    pageContext.setSelectionKind('customer', ['C1'], { C1: '张伟' });
    renderAgent();
    openPanel();
    submit('他呢');
    await waitFor(() => expect(askMock).toHaveBeenCalled());
    const payload = askMock.mock.calls[0][1] as Record<string, unknown>;
    expect(payload).toMatchObject({
      route: '/analytics',
      sessionId: 's-test',
      selection: { customer: ['C1'] },
      selectionLabels: { customer: { C1: '张伟' } },
    });
  });
});
