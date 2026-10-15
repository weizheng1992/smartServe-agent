import { render } from '@testing-library/react';
import { act } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useWorkbenchState } from './workbench';

// 审批原因直传契约钉(2026-10-15 快修):handleApprovalAction(id, 'reject', reason)
// 必须把用户填写的原因放进 POST body —— 此前审批抽屉 onReject 先写
// setRejectionReasons 再调用,stale closure 使原因被吞成机器兜底文案
// (工单 04 同病灶;RejectDialog 已修直传,抽屉接线这次收口)。
// workbench 的 fetcher = authedFetch(@/lib/api),桩在此截获 POST body。

const mocks = vi.hoisted(() => ({
  authedFetch: vi.fn(),
  ordersList: vi.fn(),
  approvalsList: vi.fn(),
  convsList: vi.fn(),
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
      conversations: { ...actual.api.conversations, list: mocks.convsList },
    },
  };
});

const emptyOk = { ok: true, json: async () => ({ success: true }) };
mocks.ordersList.mockResolvedValue({ success: true, orders: [], auditLogs: [] });
mocks.approvalsList.mockResolvedValue({ success: true, approvals: [] });
mocks.convsList.mockResolvedValue({ success: true, conversations: [] });

function Harness({ onReady }: { onReady: (w: ReturnType<typeof useWorkbenchState>) => void }) {
  const w = useWorkbenchState('approvals');
  onReady(w);
  return null;
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
