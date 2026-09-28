import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { DeskConversation } from './live-desk-model';
import { ConversationRow, DeskStateBadge } from './live-desk-parts';

const ME = 'agent@aurora';

function conv(overrides: Partial<DeskConversation> = {}): DeskConversation {
  return {
    threadId: 't1',
    userId: 'user-1',
    status: 'active',
    assignedOperatorId: null,
    metadata: null,
    updatedAt: '2026-09-25T10:00:00Z',
    ...overrides,
  };
}

describe('DeskStateBadge 状态条', () => {
  it('四态文案', () => {
    const { rerender } = render(<DeskStateBadge conversation={conv()} myEmail={ME} />);
    expect(screen.getByTestId('desk-state-badge')).toHaveTextContent('AI 托管中');

    rerender(
      <DeskStateBadge conversation={conv({ status: 'human_takeover', assignedOperatorId: null })} myEmail={ME} />,
    );
    expect(screen.getByTestId('desk-state-badge')).toHaveTextContent('排队中');

    rerender(<DeskStateBadge conversation={conv({ status: 'human_takeover', assignedOperatorId: ME })} myEmail={ME} />);
    expect(screen.getByTestId('desk-state-badge')).toHaveTextContent('我接管中');

    rerender(
      <DeskStateBadge
        conversation={conv({ status: 'human_takeover', assignedOperatorId: 'peer@aurora' })}
        myEmail={ME}
      />,
    );
    expect(screen.getByTestId('desk-state-badge')).toHaveTextContent('同事接管中');
  });

  it('排队态附等待计时(nowMs 传入时)', () => {
    const requested = '2026-09-25T10:00:00Z';
    render(
      <DeskStateBadge
        conversation={conv({
          status: 'human_takeover',
          assignedOperatorId: null,
          metadata: { takeover_requested_at: requested },
        })}
        myEmail={ME}
        nowMs={Date.parse(requested) + 65_000}
      />,
    );
    expect(screen.getByTestId('desk-state-badge')).toHaveTextContent('1:05');
  });
});

describe('ConversationRow 列表行', () => {
  it('排队态显示认领按钮,点击回调且不冒泡开卡', async () => {
    const onOpen = vi.fn();
    const onClaim = vi.fn();
    render(
      <ConversationRow
        conversation={conv({ status: 'human_takeover', assignedOperatorId: null })}
        myEmail={ME}
        onOpen={onOpen}
        onClaim={onClaim}
      />,
    );
    fireEvent.click(screen.getByTestId('claim-button'));
    expect(onClaim).toHaveBeenCalledWith('t1');
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('非排队态无认领按钮;点行打开', async () => {
    const onOpen = vi.fn();
    const onClaim = vi.fn();
    render(<ConversationRow conversation={conv()} myEmail={ME} onOpen={onOpen} onClaim={onClaim} />);
    expect(screen.queryByTestId('claim-button')).toBeNull();
    fireEvent.click(screen.getByTestId('conversation-row'));
    expect(onOpen).toHaveBeenCalledWith('t1');
  });

  it('未读徽标显示条数,无未读不渲染', () => {
    const { rerender } = render(
      <ConversationRow conversation={conv({ unreadCount: 3 })} myEmail={ME} onOpen={vi.fn()} onClaim={vi.fn()} />,
    );
    expect(screen.getByTestId('unread-badge')).toHaveTextContent('3');
    rerender(
      <ConversationRow conversation={conv({ unreadCount: 0 })} myEmail={ME} onOpen={vi.fn()} onClaim={vi.fn()} />,
    );
    expect(screen.queryByTestId('unread-badge')).toBeNull();
  });
});
