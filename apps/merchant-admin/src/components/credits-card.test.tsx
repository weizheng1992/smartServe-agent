import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CreditsCard } from './credits-card';

// 只读积分卡契约钉(2026-10-21 用量配额闸):null 余额诚实「未开通」严禁编 0、
// 流水正负着色 + 台账人话、最近 10 条截断、失败诚实可重试。

const getMock = vi.fn();
vi.mock('@/lib/api', () => ({
  api: { credits: { get: (...args: unknown[]) => getMock(...args) } },
}));

type Tx = { id: string; delta: number; reason: string; refJobId: string | null; operator: string | null; createdAt: string | null };

function makeDetail({
  balance = 987 as number | null,
  transactions = [
    { id: 't1', delta: 100, reason: 'admin_adjust: 双十一活动赠送', refJobId: null, operator: 'platform@aurora', createdAt: '2026-10-20T10:00:00Z' },
    { id: 't2', delta: -1, reason: 'consume', refJobId: 'job-1', operator: null, createdAt: '2026-10-21T08:00:00Z' },
  ] as Tx[],
} = {}) {
  return { businessId: 'aurora', balance, transactions };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('CreditsCard(服务额度只读卡)', () => {
  it('渲染余额与流水:正负着色、台账人话、操作人', async () => {
    getMock.mockResolvedValue({ success: true, data: makeDetail() });
    render(<CreditsCard />);
    await waitFor(() => expect(screen.getByText('987')).toBeInTheDocument());
    const plus = screen.getByText('+100');
    expect(plus).toHaveClass('text-emerald-600');
    const minus = screen.getByText('-1');
    expect(minus).toHaveClass('text-rose-600');
    expect(screen.getByText('平台调整:双十一活动赠送')).toBeInTheDocument();
    expect(screen.getByText('问询消耗')).toBeInTheDocument();
    expect(screen.getByText('platform@aurora')).toBeInTheDocument();
  });

  it('balance null = 未开通,诚实呈现,严禁编 0', async () => {
    getMock.mockResolvedValue({ success: true, data: makeDetail({ balance: null }) });
    render(<CreditsCard />);
    await waitFor(() => expect(screen.getByText('未开通')).toBeInTheDocument());
    expect(screen.queryByText('0')).not.toBeInTheDocument();
    // 流水照常呈现(未开通 ≠ 无台账)
    await waitFor(() => expect(screen.getByText('+100')).toBeInTheDocument());
  });

  it('只展示最近 10 条(服务端最多回 20,卡内截断)', async () => {
    const rows = Array.from({ length: 12 }, (_, i) => ({
      id: `t${i}`,
      delta: 1,
      reason: 'refund',
      refJobId: `job-${i}`,
      operator: null,
      createdAt: null,
    }));
    getMock.mockResolvedValue({ success: true, data: makeDetail({ transactions: rows }) });
    render(<CreditsCard />);
    await waitFor(() => expect(screen.getAllByText('+1')).toHaveLength(10));
  });

  it('空流水诚实「暂无流水记录」', async () => {
    getMock.mockResolvedValue({ success: true, data: makeDetail({ transactions: [] }) });
    render(<CreditsCard />);
    await waitFor(() => expect(screen.getByText('暂无流水记录')).toBeInTheDocument());
  });

  it('缺 createdAt 诚实呈现「—」,不编造时间', async () => {
    getMock.mockResolvedValue({
      success: true,
      data: makeDetail({
        transactions: [{ id: 'x', delta: 5, reason: 'initial_grant', refJobId: null, operator: null, createdAt: null }],
      }),
    });
    render(<CreditsCard />);
    await waitFor(() => expect(screen.getByText('初始赠送')).toBeInTheDocument());
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('业务失败体:诚实呈现 error 文案可重试,重试成功恢复', async () => {
    getMock.mockResolvedValueOnce({ success: false, error: '员工身份无效' });
    render(<CreditsCard />);
    await waitFor(() => expect(screen.getByText('员工身份无效')).toBeInTheDocument());
    getMock.mockResolvedValueOnce({ success: true, data: makeDetail() });
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(screen.getByText('987')).toBeInTheDocument());
  });

  it('传输失败(throw):诚实报错不崩溃', async () => {
    getMock.mockRejectedValue(new Error('gateway down'));
    render(<CreditsCard />);
    await waitFor(() => expect(screen.getByText('gateway down')).toBeInTheDocument());
  });
});
