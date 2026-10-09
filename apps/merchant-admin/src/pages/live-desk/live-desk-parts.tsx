// 坐席台纯展示件(live-desk-rework P2):状态条与列表行不携带 socket/请求
// 副作用,便于 vitest 就近单测(排序/认领/状态条验收锚点)。
import { Button } from 'ui';

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

/** 头像圆标按会话状态配色:排队琥珀 / 我的翡翠 / 同事天蓝 / AI 灰。 */
const AVATAR_STYLES: Record<DeskState, string> = {
  ai: 'bg-zinc-200 text-zinc-500',
  queuing: 'bg-amber-400 text-white',
  mine: 'bg-emerald-500 text-white',
  others: 'bg-sky-400 text-white',
};

/** 排队等待分级:>5min 红(久等告警)/ >1min 琥珀 / 其余绿(刚到)。 */
export function waitTone(waitSeconds: number): string {
  if (waitSeconds >= 300) return 'bg-red-500 text-white';
  if (waitSeconds >= 60) return 'bg-amber-500 text-white';
  return 'bg-emerald-500 text-white';
}

/** 顾客首字母头像圆标(取标识首个字形,数字/字母/中文皆可)。 */
function AvatarCircle({ label, state }: { label: string; state: DeskState }) {
  const glyph = [...label.trim()][0]?.toUpperCase() || '?';
  return (
    <span
      aria-hidden
      className={`flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full text-[13px] font-semibold ${AVATAR_STYLES[state]}`}
    >
      {glyph}
    </span>
  );
}

/** 状态条:四态徽标;排队中附等待计时(按等待时长分级变色,久等醒目)。 */
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
      className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] ${STATE_STYLES[state]}`}
    >
      {DESK_STATE_LABEL[state]}
      {state === 'queuing' && wait !== null && (
        <span className={`rounded-full px-1.5 tabular-nums ${waitTone(wait)}`}>{formatWait(wait)}</span>
      )}
    </span>
  );
}

/** 左栏会话行:头像圆标 + 状态条 + 未读徽标 + 认领按钮(仅排队态)。 */
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
    <Button
      type="button"
      variant="ghost"
      data-testid="conversation-row"
      onClick={() => onOpen(conversation.threadId)}
      className={`flex w-full cursor-pointer items-center justify-start gap-2.5 rounded-xl border px-2.5 py-2 text-left font-normal ${
        selected ? 'border-zinc-900 bg-zinc-50 shadow-sm hover:bg-zinc-50' : 'border-transparent hover:bg-zinc-50'
      }`}
    >
      <AvatarCircle label={conversation.userId || conversation.threadId} state={state} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center justify-between gap-2">
          <span className="truncate text-[13px] font-medium text-zinc-800">
            {conversation.userId || conversation.threadId}
          </span>
          <DeskStateBadge conversation={conversation} myEmail={myEmail} nowMs={nowMs} />
        </span>
        <span className="mt-1 flex items-center justify-between gap-2">
          <span className="truncate text-[11px] text-zinc-400">{conversation.lastMessageSnippet || '—'}</span>
          {unread > 0 && (
            <span
              data-testid="unread-badge"
              className="shrink-0 rounded-full bg-red-500 px-1.5 text-[10px] font-medium text-white"
            >
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
              className="shrink-0 cursor-pointer rounded-full bg-zinc-900 px-2.5 py-0.5 text-[11px] text-white transition-colors hover:bg-zinc-700 disabled:opacity-50"
            >
              {claiming ? '认领中…' : '认领'}
            </span>
          )}
        </span>
      </span>
    </Button>
  );
}
