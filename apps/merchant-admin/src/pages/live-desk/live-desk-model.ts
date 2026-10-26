// 坐席台纯函数层(live-desk-rework P2):状态派生 / 队列排序 / 筛选。
// 服务端 threads 真源形状(status + assigned_operator_id + metadata.
// takeover_requested_at)经 GET /api/conversations 透传,这里只做无副作用
// 派生 —— 排序是**客户端**口径(等待最久置顶),服务端 ORDER BY updated_at
// DESC 保持不变(spec §2.3 裁决)。

export interface DeskConversation {
  threadId: string;
  userId?: string | null;
  status: string;
  assignedOperatorId?: string | null;
  unreadCount?: number;
  metadata?: Record<string, unknown> | null;
  tags?: string[];
  lastMessageSnippet?: string | null;
  lastMessageRole?: string | null;
  updatedAt?: string;
  createdAt?: string;
}

/** 坐席视角四态:AI 托管 / 排队中(呼叫无人认领)/ 我接管 / 同事接管。 */
export type DeskState = 'ai' | 'queuing' | 'mine' | 'others';

export type DeskTab = 'all' | 'queuing' | 'mine';

export function deriveConversationState(
  c: Pick<DeskConversation, 'status' | 'assignedOperatorId'>,
  myEmail: string,
): DeskState {
  if (c.status !== 'human_takeover') return 'ai';
  // 真源复合语义:接管态 + 坐席空 = 呼叫中/排队
  if (!c.assignedOperatorId) return 'queuing';
  return c.assignedOperatorId === myEmail ? 'mine' : 'others';
}

/** 呼叫时刻(unix ms):metadata.takeover_requested_at,缺/坏回 null。 */
export function takeoverRequestedAt(c: Pick<DeskConversation, 'metadata'>): number | null {
  const raw = c.metadata?.takeover_requested_at;
  if (typeof raw !== 'string' && typeof raw !== 'number') return null;
  const t = new Date(raw).getTime();
  return Number.isFinite(t) ? t : null;
}

/** 排队已等待秒数;非排队态回 null。 */
export function queueWaitSeconds(
  c: Pick<DeskConversation, 'status' | 'assignedOperatorId' | 'metadata'>,
  nowMs: number,
): number | null {
  if (deriveConversationState(c, '__any__') !== 'queuing') return null;
  const t = takeoverRequestedAt(c);
  if (t === null) return null;
  return Math.max(0, Math.floor((nowMs - t) / 1000));
}

/** 等待 mm:ss(排队计时/状态条展示)。 */
export function formatWait(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, '0')}`;
}

/** 列表行相对时间(2026-10-24 列表优化):今天 HH:mm / 昨天 / 今年 M月D日 /
 *  跨年 YYYY/M/D;缺值/坏值回空串(诚实空,调用侧不渲染)。nowMs 注入便于测试。 */
export function formatUpdatedAt(iso?: string | null, nowMs?: number): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date(nowMs ?? Date.now());
  const two = (n: number) => String(n).padStart(2, '0');
  if (d.toDateString() === now.toDateString()) {
    return `${two(d.getHours())}:${two(d.getMinutes())}`;
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return '昨天';
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日`;
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

/**
 * 列表排序:排队中置顶且等待最久优先(呼叫即工单,先到先接);其余按
 * updatedAt DESC(与列表接口默认序一致)。原地不修改入参。
 */
export function sortQueueFirst(list: DeskConversation[]): DeskConversation[] {
  const updated = (c: DeskConversation) => new Date(c.updatedAt || 0).getTime();
  return [...list].sort((a, b) => {
    const qa = takeoverRequestedAt(a);
    const qb = takeoverRequestedAt(b);
    const aQueuing = a.status === 'human_takeover' && !a.assignedOperatorId;
    const bQueuing = b.status === 'human_takeover' && !b.assignedOperatorId;
    if (aQueuing && bQueuing) return (qa ?? 0) - (qb ?? 0); // 等最久在顶
    if (aQueuing !== bQueuing) return aQueuing ? -1 : 1;
    return updated(b) - updated(a);
  });
}

/** 左栏筛选:tab(全部/排队中/我的)+ 关键词(threadId/用户/末条消息)。 */
export function filterConversations(
  list: DeskConversation[],
  myEmail: string,
  tab: DeskTab,
  keyword: string,
): DeskConversation[] {
  const kw = keyword.trim().toLowerCase();
  return list.filter((c) => {
    const state = deriveConversationState(c, myEmail);
    if (tab === 'queuing' && state !== 'queuing') return false;
    if (tab === 'mine' && state !== 'mine') return false;
    if (!kw) return true;
    return (
      c.threadId.toLowerCase().includes(kw) ||
      (c.userId || '').toLowerCase().includes(kw) ||
      (c.lastMessageSnippet || '').toLowerCase().includes(kw)
    );
  });
}

export const DESK_STATE_LABEL: Record<DeskState, string> = {
  ai: 'AI 托管中',
  queuing: '排队中',
  mine: '我接管中',
  others: '同事接管中',
};

/** 「全部」tab 的分组节序(2026-10-25 左栏重构):紧急度降序 —— 排队最优先
 *  (呼叫即工单)、其次我接管的、再同事、AI 托管长尾殿后;消灭无差别长列表。 */
export const DESK_GROUP_ORDER: DeskState[] = ['queuing', 'mine', 'others', 'ai'];

export interface DeskStateGroup {
  state: DeskState;
  label: string;
  rows: DeskConversation[];
}

/** 按坐席四态分组(保持入参顺序,排序仍归 sortQueueFirst 单点);空组不产出。 */
export function groupByState(list: DeskConversation[], myEmail: string): DeskStateGroup[] {
  const buckets = new Map<DeskState, DeskConversation[]>();
  for (const c of list) {
    const state = deriveConversationState(c, myEmail);
    const bucket = buckets.get(state);
    if (bucket) bucket.push(c);
    else buckets.set(state, [c]);
  }
  return DESK_GROUP_ORDER.filter((s) => buckets.has(s)).map((s) => ({
    state: s,
    label: DESK_STATE_LABEL[s],
    rows: buckets.get(s) || [],
  }));
}
