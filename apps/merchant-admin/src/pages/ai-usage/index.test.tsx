import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AiUsagePage from './index';

// AI 用量页(零 DB):api.aiUsage / api.credits 全桩,errMsgOf 走真实现
// (importActual 展开)—— 断言编排与诚实呈现,不测网络。
const summaryMock = vi.fn();
const turnsMock = vi.fn();
const callsMock = vi.fn();
const creditsMock = vi.fn();

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      aiUsage: {
        summary: (...a: unknown[]) => summaryMock(...a),
        turns: (...a: unknown[]) => turnsMock(...a),
        calls: (...a: unknown[]) => callsMock(...a),
      },
      credits: { get: (...a: unknown[]) => creditsMock(...a) },
    },
  };
});

const summaryBody = {
  success: true,
  data: {
    businessId: 'aurora',
    quota: { monthlyLimitTokens: 5_000_000, usedTokens: 123_456, usageRate: 0.0247 },
    turns: { total: 210, avgLatencyMs: 4230, zeroLlmRate: 0.5, fastPathRate: 0.75 },
    byDay: [
      { day: '2026-10-01', tokens: 100, turns: 2 },
      { day: '2026-10-02', tokens: 200, turns: 3 },
      { day: '2026-10-03', tokens: 300, turns: 4 },
    ],
    byPath: [
      { path: 'deep_path', turns: 105, tokens: 100_000 },
      { path: 'greeting', turns: 60, tokens: 0 },
      { path: 'semantic_cache', turns: 45, tokens: 23_456 },
    ],
    calls: { total: 300, totalTokens: 90_000, avgLatencyMs: 1200 },
    taskHealth: {
      totalTurns: 210,
      resolvedTurns: 189,
      completionRate: 0.9,
      clarifyTurns: 12,
      clarifyFollowupAccuracy: 0.8333,
      clarifyFollowupCompleted: 10,
      clarifyFollowupReclarified: 2,
      toolErrorTurnRate: 0.05,
      duplicateBypassRate: 0.02,
      avgTokensPerTurn: 620.5,
    },
    notes: ['data agent 等图外调用量暂未按租户归因,不在本页口径内(归因修复排期 P1)'],
  },
};

const turnsBody = {
  success: true,
  data: {
    turns: [
      {
        jobId: 'job-1',
        threadId: 't1',
        turnPath: 'deep_path',
        totalTokens: 1234,
        latencyMs: 1523,
        resolutionStatus: 'resolved_auto',
        createdAt: '2026-10-24T10:00:00',
      },
      {
        jobId: null,
        threadId: 't0',
        turnPath: null,
        totalTokens: 0,
        latencyMs: 45,
        resolutionStatus: 'resolved_auto',
        createdAt: '2026-10-23T09:00:00',
      },
    ],
  },
};

const callsBody = {
  success: true,
  data: {
    jobId: 'job-1',
    threadId: 't1',
    turnPath: 'deep_path',
    calls: [
      { node: 'planner', model: 'glm-test', tokensIn: 800, tokensOut: 200, totalTokens: 1000, latencyMs: 900, createdAt: null },
      { node: 'finish', model: 'glm-test', tokensIn: 500, tokensOut: 100, totalTokens: 600, latencyMs: 700, createdAt: null },
    ],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  summaryMock.mockResolvedValue(summaryBody);
  turnsMock.mockResolvedValue(turnsBody);
  callsMock.mockResolvedValue(callsBody);
  creditsMock.mockResolvedValue({ success: true, data: { businessId: 'aurora', balance: 42, transactions: [] } });
});

describe('AiUsagePage', () => {
  it('渲染 KPI 与路径分布,无美元口径注记在场', async () => {
    render(<AiUsagePage />);
    await waitFor(() => expect(screen.getByText('123,456')).toBeInTheDocument());
    expect(screen.getByText(/限额 5,000,000 · 已用 2.5%/)).toBeInTheDocument();
    expect(screen.getByText('50.0%')).toBeInTheDocument();
    expect(screen.getByText('75.0%')).toBeInTheDocument();
    // byPath 中文标签(turn_path 闭集映射;「全管线」同时命中条形图与轮次行,用 getAll)
    expect(screen.getAllByText('全管线').length).toBeGreaterThan(0);
    expect(screen.getByText('极速问候')).toBeInTheDocument();
    expect(screen.getByText('同问缓存命中')).toBeInTheDocument();
    // 轮行如实呈现
    expect(screen.getByText('1,234')).toBeInTheDocument();
    expect(screen.getByText('无关联(历史轮)')).toBeInTheDocument();
    // 口径注记 + 无美元声明 + 积分卡复用
    expect(screen.getByText(/data agent 等图外调用量暂未按租户归因/)).toBeInTheDocument();
    expect(screen.getByText(/本页不展示美元成本/)).toBeInTheDocument();
    expect(screen.getByLabelText('服务额度(积分)')).toBeInTheDocument();
    expect(summaryMock).toHaveBeenCalled();
  });

  it('多轮任务健康度四指标卡:数值如实呈现,无后继澄清诚实缺省 —', async () => {
    render(<AiUsagePage />);
    await waitFor(() => expect(screen.getByText('任务完成率')).toBeInTheDocument());
    expect(screen.getByText('90.0%')).toBeInTheDocument(); // completionRate
    expect(screen.getByText('resolved_auto 189 / 210 轮')).toBeInTheDocument();
    expect(screen.getByText('83.3%')).toBeInTheDocument(); // clarifyFollowupAccuracy
    expect(screen.getByText(/本月澄清 12 轮/)).toBeInTheDocument();
    expect(screen.getByText('5.0%')).toBeInTheDocument(); // toolErrorTurnRate
    expect(screen.getByText('2.0%')).toBeInTheDocument(); // duplicateBypassRate
    expect(screen.getByText('620.5')).toBeInTheDocument(); // avgTokensPerTurn 原样呈现
    // null 口径诚实缺省(P1-2):改桩后渲染 — 而非编造 0%
    summaryMock.mockResolvedValue({
      ...summaryBody,
      data: { ...summaryBody.data, taskHealth: { ...summaryBody.data.taskHealth, clarifyFollowupAccuracy: null } },
    });
    render(<AiUsagePage />);
    await waitFor(() => expect(screen.getAllByText('—').length).toBeGreaterThan(0));
  });

  it('点行下钻调用明细:按 jobId 精确取数并渲染节点行', async () => {
    render(<AiUsagePage />);
    const btn = await screen.findByRole('button', { name: '调用明细' });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText('planner')).toBeInTheDocument());
    expect(screen.getByText('finish')).toBeInTheDocument();
    expect(callsMock).toHaveBeenCalledWith('job-1');
  });

  it('零 LLM 轮下钻诚实空:0 次调用文案,不编造节点', async () => {
    callsMock.mockResolvedValue({
      success: true,
      data: { jobId: 'job-1', threadId: 't1', turnPath: 'greeting', calls: [] },
    });
    render(<AiUsagePage />);
    const btn = await screen.findByRole('button', { name: '调用明细' });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText(/本轮 0 次 LLM 调用/)).toBeInTheDocument());
  });

  it('summary 业务失败:errMsgOf 文案如实呈现 + 重试在手', async () => {
    summaryMock.mockResolvedValue({ success: false, message: '租户上下文缺失' });
    render(<AiUsagePage />);
    await waitFor(() => expect(screen.getByText('租户上下文缺失')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });
});
