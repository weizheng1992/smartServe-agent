import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import ReportsPage from './index';

vi.mock('@/lib/api', () => ({
  api: {
    reports: {
      list: vi.fn(),
      create: vi.fn(),
      csv: vi.fn(),
      detail: vi.fn(),
    },
  },
}));

import { api } from '@/lib/api';
const reports = api.reports as unknown as {
  list: ReturnType<typeof vi.fn>;
  detail: ReturnType<typeof vi.fn>;
  csv: ReturnType<typeof vi.fn>;
};

const ROWS = { volume: [{ productId: 'A', metricScore: 3 }, { productId: 'B', metricScore: 5 }] };

beforeEach(() => {
  vi.clearAllMocks();
  reports.list.mockResolvedValue({ reports: [
    { id: 'r1', title: '品类GMV排行', timeWindow: '{"source":"agent_result","chart":"bar"}', createdAt: '2026-09-23' },
  ] });
  reports.detail.mockResolvedValue({ success: true, id: 'r1', title: '品类GMV排行', chart: 'bar', rows: ROWS });
  reports.csv.mockResolvedValue({ filename: 'r1.csv', csv: '\ufeffa,b\n1,2' });
  // Blob/anchor 桩:jsdom 无下载语义
  Object.defineProperty(URL, 'createObjectURL', { value: () => 'blob:x', writable: true });
  HTMLAnchorElement.prototype.click = vi.fn();
});

describe('ReportsPage(我的报告 + 图表重放)', () => {
  it('列表渲染并标注「来自对话结果」', async () => {
    render(<MemoryRouter><ReportsPage /></MemoryRouter>);
    expect(await screen.findByText('品类GMV排行')).toBeInTheDocument();
    expect(screen.getByText(/来自对话结果/)).toBeInTheDocument();
  });

  it('展开图表:拉详情并按存档图型重绘(条形图)', async () => {
    render(<MemoryRouter><ReportsPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '展开图表' }));
    await waitFor(() => expect(reports.detail).toHaveBeenCalledWith('r1'));
    expect(await screen.findByLabelText('排行条形图')).toBeInTheDocument();
  });

  it('下载 CSV:以 BOM 文本建 Blob', async () => {
    render(<MemoryRouter><ReportsPage /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: '下载 CSV' }));
    await waitFor(() => expect(reports.csv).toHaveBeenCalledWith('r1'));
    await waitFor(() => expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled());
  });

  it('空列表走引导文案', async () => {
    reports.list.mockResolvedValue({ reports: [] });
    render(<MemoryRouter><ReportsPage /></MemoryRouter>);
    expect(await screen.findByText(/暂无报告/)).toBeInTheDocument();
  });
});
