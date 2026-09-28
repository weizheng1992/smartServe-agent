import { describe, expect, it } from 'vitest';

import {
  DESK_STATE_LABEL,
  type DeskConversation,
  deriveConversationState,
  filterConversations,
  formatWait,
  queueWaitSeconds,
  sortQueueFirst,
  takeoverRequestedAt,
} from './live-desk-model';

const ME = 'agent@aurora';

function conv(overrides: Partial<DeskConversation> = {}): DeskConversation {
  return {
    threadId: 't1',
    status: 'active',
    assignedOperatorId: null,
    metadata: null,
    updatedAt: '2026-09-25T10:00:00Z',
    ...overrides,
  };
}

describe('deriveConversationState 四态', () => {
  it('非接管态 → ai', () => {
    expect(deriveConversationState(conv({ status: 'active' }), ME)).toBe('ai');
    expect(deriveConversationState(conv({ status: 'closed' }), ME)).toBe('ai');
  });

  it('接管态+坐席空 → queuing(真源复合语义)', () => {
    expect(deriveConversationState(conv({ status: 'human_takeover', assignedOperatorId: null }), ME)).toBe('queuing');
  });

  it('接管态按坐席邮箱分 mine/others', () => {
    const c = conv({ status: 'human_takeover', assignedOperatorId: ME });
    expect(deriveConversationState(c, ME)).toBe('mine');
    expect(deriveConversationState(c, 'peer@aurora')).toBe('others');
  });
});

describe('排队计时', () => {
  const requested = '2026-09-25T10:00:00Z';

  it('takeoverRequestedAt 解析 metadata,缺/坏回 null', () => {
    expect(takeoverRequestedAt(conv({ metadata: { takeover_requested_at: requested } }))).toBe(Date.parse(requested));
    expect(takeoverRequestedAt(conv({ metadata: {} }))).toBeNull();
    expect(takeoverRequestedAt(conv({ metadata: { takeover_requested_at: 'garbage' } }))).toBeNull();
    expect(takeoverRequestedAt(conv({ metadata: null }))).toBeNull();
  });

  it('queueWaitSeconds 仅排队态计时', () => {
    const now = Date.parse(requested) + 65_000;
    const queuing = conv({
      status: 'human_takeover',
      assignedOperatorId: null,
      metadata: { takeover_requested_at: requested },
    });
    expect(queueWaitSeconds(queuing, now)).toBe(65);
    expect(
      queueWaitSeconds(conv({ status: 'active', metadata: { takeover_requested_at: requested } }), now),
    ).toBeNull();
  });

  it('formatWait mm:ss 补零', () => {
    expect(formatWait(0)).toBe('0:00');
    expect(formatWait(65)).toBe('1:05');
    expect(formatWait(600)).toBe('10:00');
  });
});

describe('sortQueueFirst:排队等待最久置顶', () => {
  const t = (min: number) => new Date(Date.parse('2026-09-25T10:00:00Z') + min * 60_000).toISOString();

  it('排队组按 takeover_requested_at 升序置顶,其余 updatedAt DESC', () => {
    const list = [
      conv({ threadId: 'mine-new', status: 'human_takeover', assignedOperatorId: ME, updatedAt: t(30) }),
      conv({
        threadId: 'q-old',
        status: 'human_takeover',
        assignedOperatorId: null,
        metadata: { takeover_requested_at: t(10) },
        updatedAt: t(30),
      }),
      conv({ threadId: 'ai-chat', status: 'active', updatedAt: t(20) }),
      conv({
        threadId: 'q-new',
        status: 'human_takeover',
        assignedOperatorId: null,
        metadata: { takeover_requested_at: t(25) },
        updatedAt: t(28),
      }),
    ];
    expect(sortQueueFirst(list).map((c) => c.threadId)).toEqual(['q-old', 'q-new', 'mine-new', 'ai-chat']);
  });

  it('不改入参数组', () => {
    const list = [conv({ threadId: 'a', updatedAt: t(1) }), conv({ threadId: 'b', updatedAt: t(2) })];
    sortQueueFirst(list);
    expect(list.map((c) => c.threadId)).toEqual(['a', 'b']);
  });
});

describe('filterConversations:tab + 关键词', () => {
  const queuing = conv({
    threadId: 'thread-q',
    userId: 'user-q',
    status: 'human_takeover',
    assignedOperatorId: null,
    lastMessageSnippet: '有人吗',
  });
  const mine = conv({
    threadId: 'thread-m',
    status: 'human_takeover',
    assignedOperatorId: ME,
    lastMessageSnippet: '好的',
  });
  const other = conv({
    threadId: 'thread-o',
    status: 'human_takeover',
    assignedOperatorId: 'peer@aurora',
    lastMessageSnippet: '发货了',
  });
  const ai = conv({ threadId: 'thread-ai', status: 'active', lastMessageSnippet: '推荐一款' });
  const all = [queuing, mine, other, ai];

  it('tab 三态各取所需', () => {
    expect(filterConversations(all, ME, 'all', '').map((c) => c.threadId)).toEqual([
      'thread-q',
      'thread-m',
      'thread-o',
      'thread-ai',
    ]);
    expect(filterConversations(all, ME, 'queuing', '').map((c) => c.threadId)).toEqual(['thread-q']);
    expect(filterConversations(all, ME, 'mine', '').map((c) => c.threadId)).toEqual(['thread-m']);
  });

  it('关键词命中 threadId/用户/末条消息,大小写不敏感', () => {
    expect(filterConversations(all, ME, 'all', 'THREAD-Q').map((c) => c.threadId)).toEqual(['thread-q']);
    expect(filterConversations(all, ME, 'all', 'user-q').map((c) => c.threadId)).toEqual(['thread-q']);
    expect(filterConversations(all, ME, 'all', '发货').map((c) => c.threadId)).toEqual(['thread-o']);
    expect(filterConversations(all, ME, 'all', '不存在的词')).toEqual([]);
  });
});

describe('状态条文案', () => {
  it('四态齐备', () => {
    expect(DESK_STATE_LABEL.ai).toContain('AI');
    expect(DESK_STATE_LABEL.queuing).toBe('排队中');
    expect(DESK_STATE_LABEL.mine).toContain('我');
    expect(DESK_STATE_LABEL.others).toContain('同事');
  });
});
