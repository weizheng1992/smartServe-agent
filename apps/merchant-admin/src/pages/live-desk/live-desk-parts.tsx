// 坐席台纯展示件(live-desk-rework P2):状态条与列表行不携带 socket/请求
// 副作用,便于 vitest 就近单测(排序/认领/状态条验收锚点)。
import type { DeskConversation } from './live-desk-model';
import {
  DESK_STATE_LABEL,
  type DeskState,
  deriveConversationState,
  formatWait,
  queueWaitSeconds,
} from './live-desk-model';

const STATE_STYLES: Record<DeskState, string> = {
  ai: 'bg-zinc-100 text-zinc-500',
  queuing: 'bg-amber-100 text-amber-700',
  mine: 'bg-emerald-100 text-emerald-700',
  others: 'bg-sky-100 text-sky-700',
};

/** 状态条:四态徽标;排队中附等待计时(等待最久置顶的可见口径)。 */
export function DeskStateBadge({
  conversation,
  myEmail,
  nowMs,
}: {
  conversation: Pick<DeskConversation, 'status' | 'assignedOperatorId' | 'metadata'>;
  myEmail: string;
  nowMs?: number;
}) {
  const state = deriveConversationState(conversation, myEmail);
  const wait = nowMs === undefined ? null : queueWaitSeconds(conversation, nowMs);
  return (
    <span
      data-testid="desk-state-badge"
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ${STATE_STYLES[state]}`}
    >
      {DESK_STATE_LABEL[state]}
      {state === 'queuing' && wait !== null && <span className="tabular-nums">{formatWait(wait)}</span>}
    </span>
  );
}

/** 左栏会话行:状态条 + 未读徽标 + 认领按钮(仅排队态)。 */
export function ConversationRow({
  conversation,
  myEmail,
  nowMs,
  selected,
  claiming,
  onOpen,
  onClaim,
}: {
  conversation: DeskConversation;
  myEmail: string;
  nowMs?: number;
  selected?: boolean;
  claiming?: boolean;
  onOpen: (threadId: string) => void;
  onClaim: (threadId: string) => void;
}) {
  const state = deriveConversationState(conversation, myEmail);
  const unread = conversation.unreadCount || 0;
  return (
    <button
      type="button"
      data-testid="conversation-row"
      onClick={() => onOpen(conversation.threadId)}
      className={`block w-full cursor-pointer rounded-lg border px-3 py-2 text-left ${
        selected ? 'border-zinc-900 bg-zinc-50' : 'border-transparent hover:bg-zinc-50'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[13px] font-medium text-zinc-800">
          {conversation.userId || conversation.threadId}
        </span>
        <DeskStateBadge conversation={conversation} myEmail={myEmail} nowMs={nowMs} />
      </div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="truncate text-[11px] text-zinc-400">{conversation.lastMessageSnippet || '—'}</span>
        {unread > 0 && (
          <span data-testid="unread-badge" className="shrink-0 rounded-full bg-red-500 px-1.5 text-[10px] text-white">
            {unread}
          </span>
        )}
        {state === 'queuing' && (
          <span
            role="button"
            tabIndex={0}
            data-testid="claim-button"
            aria-label={`认领会话 ${conversation.threadId}`}
            onClick={(e) => {
              e.stopPropagation();
              onClaim(conversation.threadId);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.stopPropagation();
                onClaim(conversation.threadId);
              }
            }}
            className="shrink-0 cursor-pointer rounded bg-zinc-900 px-2 py-0.5 text-[11px] text-white disabled:opacity-50"
          >
            {claiming ? '认领中…' : '认领'}
          </span>
        )}
      </div>
    </button>
  );
}
