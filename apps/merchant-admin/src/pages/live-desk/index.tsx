import type { MessageItem } from '@/lib/api';
import { useLayoutEffect, useMemo, useRef, useState } from 'react';
// 坐席台独立页(live-desk-rework P2/P3/P4):台面顶栏(排队/我的计数 + 实时
// 连接态)+ 三栏 —— 左会话池(排队等待最久置顶)/ 中时间线(认领后回复 +
// 待批工单批驳卡)/ 右坐席上下文栏(五项,spec §2.4)+ 坐席在线态。
// 旧 /live-desk tab(OrderWorkbench)并存不动作回退面;本页是 spec §3 P2-P4
// 的正式坐席工作台。e2e/vitest 锚点(testid 与关键文本)一概保留。
import { Button } from 'ui';
import {
  ContextCustomer,
  ContextNotes,
  ContextOrders,
  ContextProfile,
  ContextSection,
  ContextTickets,
} from './live-desk-context-parts';
import { type DeskTab, deriveConversationState, filterConversations, sortQueueFirst } from './live-desk-model';
import { ConversationRow, DeskStateBadge } from './live-desk-parts';
import { useLiveDesk } from './use-live-desk';

const TABS: Array<{ key: DeskTab; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'queuing', label: '排队中' },
  { key: 'mine', label: '我的' },
];

/** PG TIMESTAMP naive isoformat(无 Z/时区,空格分隔 Safari 不吃)→ HH:MM。 */
function fmtClock(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

const sameDay = (iso: string | null | undefined) => {
  if (!iso) return null;
  const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? null : d.toDateString();
};

/** 顾客侧首字母头像(时间线与列表行同形)。 */
function ChatAvatar({ label, className = '' }: { label: string; className?: string }) {
  const glyph = [...label.trim()][0]?.toUpperCase() || '?';
  return (
    <span
      aria-hidden
      className={`flex h-7 w-7 shrink-0 select-none items-center justify-center rounded-full bg-zinc-200 text-[11px] font-semibold text-zinc-500 ${className}`}
    >
      {glyph}
    </span>
  );
}

/** 输入中三点跳动(时间线内气泡形态)。 */
function TypingDots() {
  return (
    <span className="flex items-center gap-0.5">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1 w-1 animate-bounce rounded-full bg-zinc-400"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </span>
  );
}

/** 时间线单条消息:顾客左 / 坐席右 / AI 徽标左 / 系统居中胶囊。 */
function TimelineMessage({ m, myEmail }: { m: MessageItem; myEmail: string }) {
  const clock = fmtClock(m.timestamp);
  if (m.role === 'system') {
    return (
      <div className="flex justify-center">
        <span className="max-w-[80%] rounded-full bg-zinc-50 px-2.5 py-1 text-center text-[10px] break-words text-zinc-400">
          系统 · {m.content}
        </span>
      </div>
    );
  }
  if (m.role === 'assistant') {
    return (
      <div className="flex items-end gap-2">
        <span
          aria-hidden
          className="flex h-7 w-7 shrink-0 select-none items-center justify-center rounded-full border border-amber-200 bg-amber-50 text-[9px] font-bold text-amber-600"
        >
          AI
        </span>
        {/* 限宽挂在此层(相对整行宽),气泡 max-w-full —— 挂气泡上会被内容反撑失效 */}
        <div className="flex min-w-0 max-w-[70%] flex-col items-start">
          <div className="rounded-2xl rounded-bl-sm border border-zinc-200 bg-white px-3 py-2 text-[12px] leading-5 whitespace-pre-wrap break-words text-zinc-700">
            {m.content}
          </div>
          {clock && <div className="mt-0.5 text-[10px] text-zinc-300">{clock}</div>}
        </div>
      </div>
    );
  }
  const mine = m.role === 'operator';
  const name = mine ? m.operatorInfo?.operatorName || myEmail : m.role === 'user' ? '顾客' : m.role;
  return (
    <div className={`flex items-end gap-2 ${mine ? 'flex-row-reverse' : ''}`}>
      {mine ? (
        <span
          aria-hidden
          className="flex h-7 w-7 shrink-0 select-none items-center justify-center rounded-full bg-emerald-500 text-[11px] font-semibold text-white"
        >
          {[...(m.operatorInfo?.operatorName || myEmail)][0]?.toUpperCase() || '坐'}
        </span>
      ) : (
        <ChatAvatar label={name} />
      )}
      <div className={`flex min-w-0 max-w-[70%] flex-col ${mine ? 'items-end' : 'items-start'}`}>
        <div
          className={`max-w-full px-3 py-2 text-[12px] leading-5 ${
            mine
              ? 'rounded-2xl rounded-br-sm bg-emerald-500 text-white'
              : 'rounded-2xl rounded-bl-sm bg-zinc-100 text-zinc-800'
          }`}
        >
          {!mine && <div className="mb-0.5 text-[10px] text-zinc-400">{name}</div>}
          {mine && m.operatorInfo && <div className="mb-0.5 text-[10px] opacity-70">{name}</div>}
          <div className="whitespace-pre-wrap break-words">{m.content}</div>
        </div>
        {clock && <div className="mt-0.5 text-[10px] text-zinc-300">{clock}</div>}
      </div>
    </div>
  );
}

export default function LiveDeskPage() {
  const desk = useLiveDesk();
  const [tab, setTab] = useState<DeskTab>('all');
  const [keyword, setKeyword] = useState('');
  const [draft, setDraft] = useState('');
  const [claimingId, setClaimingId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [reviewing, setReviewing] = useState(false);

  // 时间线视口贴底(2026-09-29 实弹:聊天记录打开总停在顶部=最旧消息,
  // 最新消息沉在视口外):切换会话无条件回底部;新消息仅当操作员原本
  // 贴底(没在翻历史)才跟随,离底阅读时不劫持滚动位置。
  // 用 useLayoutEffect:提交后、绘制前写 scrollTop —— useEffect 会在
  // 绘制后瞬移,乐观气泡先以旧视口画一帧再跳底,即「发消息抖一下」。
  const timelineRef = useRef<HTMLDivElement | null>(null);
  const stickBottom = useRef(true);
  // 两处依赖均为「触发器」而非读取值(effect 体只写 scrollTop),刻意不进函数体
  // biome-ignore lint/correctness/useExhaustiveDependencies: 触发器依赖:会话切换即回底
  useLayoutEffect(() => {
    stickBottom.current = true;
    const el = timelineRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [desk.selectedThreadId]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: 触发器依赖:消息数变化即贴底跟随
  useLayoutEffect(() => {
    const el = timelineRef.current;
    if (el && stickBottom.current) el.scrollTop = el.scrollHeight;
  }, [desk.timeline.length]);

  // P4 台内批驳:批/驳都走员工代行通道,403(无 live_desk:approve)与
  // 「已处理过」(400)按服务端文案如实呈现;批驳后不自动释放,仅刷新待批卡。
  const doReview = async (action: 'approve' | 'reject') => {
    if (!desk.pendingTicket || reviewing) return;
    setReviewing(true);
    setNotice('');
    const r = await desk.reviewTicket(
      desk.pendingTicket.id,
      action,
      action === 'reject' ? rejectReason.trim() : undefined,
    );
    setReviewing(false);
    setRejectOpen(false);
    setRejectReason('');
    if (!r.success) setNotice(r.error || '批驳失败');
  };

  const visible = useMemo(
    () => sortQueueFirst(filterConversations(desk.conversations, desk.myEmail, tab, keyword)),
    [desk.conversations, desk.myEmail, tab, keyword],
  );
  // 台面顶栏计数:排队(待认领)与我的(接管中)会话数。
  const counts = useMemo(() => {
    let queuing = 0;
    let mine = 0;
    for (const c of desk.conversations) {
      const s = deriveConversationState(c, desk.myEmail);
      if (s === 'queuing') queuing += 1;
      if (s === 'mine') mine += 1;
    }
    return { queuing, mine };
  }, [desk.conversations, desk.myEmail]);

  const selected = desk.conversations.find((c) => c.threadId === desk.selectedThreadId) || null;
  const mineSelected =
    !!selected && selected.status === 'human_takeover' && selected.assignedOperatorId === desk.myEmail;

  const doClaim = async (threadId: string) => {
    setClaimingId(threadId);
    setNotice('');
    const ack = await desk.claim(threadId);
    setClaimingId(null);
    if (!ack.success) setNotice(ack.error || '认领失败');
    else await desk.openThread(threadId);
  };

  const doRelease = async () => {
    if (!desk.selectedThreadId) return;
    setNotice('');
    const ack = await desk.release(desk.selectedThreadId);
    if (!ack.success) setNotice(ack.error || '释放失败');
  };

  const doSend = async () => {
    const content = draft.trim();
    if (!content || !desk.selectedThreadId) return;
    setDraft('');
    const ack = await desk.sendMessage(desk.selectedThreadId, content);
    if (!ack.success) setNotice(ack.error || '发送失败');
  };

  const doAddNote = async (content: string) => {
    if (!desk.selectedThreadId) return;
    const r = await desk.addNote(desk.selectedThreadId, content);
    if (!r.success) setNotice(('error' in r && r.error) || '备注写入失败');
  };

  const doRemoveNote = async (noteId: string) => {
    if (!desk.selectedThreadId) return;
    await desk.removeNote(desk.selectedThreadId, noteId);
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* 台面顶栏:标题 + 排队/我的计数 + 实时连接态 */}
      <div className="flex shrink-0 items-center justify-between">
        <div className="flex items-baseline gap-2.5">
          <h1 className="text-[15px] font-semibold text-zinc-900">客服工作台</h1>
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-700 tabular-nums">
            排队 {counts.queuing}
          </span>
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] text-emerald-700 tabular-nums">
            我的 {counts.mine}
          </span>
        </div>
        <span
          className={`flex items-center gap-1.5 text-[11px] ${desk.connected ? 'text-emerald-600' : 'text-zinc-400'}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${desk.connected ? 'bg-emerald-500' : 'bg-zinc-300'}`} />
          {desk.connected ? '实时已连接' : '未连接'}
        </span>
      </div>

      <div className="flex min-h-0 flex-1 gap-4">
        {/* 左:会话池 */}
        <aside className="flex w-80 shrink-0 flex-col rounded-xl border border-zinc-200 bg-white">
          <div className="border-b border-zinc-100 p-3">
            <div className="flex gap-1">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  data-testid={`desk-tab-${t.key}`}
                  onClick={() => setTab(t.key)}
                  className={`cursor-pointer rounded-full px-2.5 py-1 text-[11px] transition-colors ${
                    tab === t.key ? 'bg-zinc-900 text-white' : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索单号 / 用户 / 消息"
              className="mt-2 w-full rounded-lg border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 text-[12px] outline-none transition-colors focus:border-zinc-300 focus:bg-white focus:ring-2 focus:ring-zinc-100"
            />
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
            {visible.length === 0 && <div className="p-4 text-center text-[12px] text-zinc-400">暂无会话</div>}
            {visible.map((c) => (
              <ConversationRow
                key={c.threadId}
                conversation={c}
                myEmail={desk.myEmail}
                nowMs={desk.now}
                selected={c.threadId === desk.selectedThreadId}
                claiming={claimingId === c.threadId}
                onOpen={(tid) => void desk.openThread(tid)}
                onClaim={(tid) => void doClaim(tid)}
              />
            ))}
          </div>
        </aside>

        {/* 中:时间线 */}
        <section className="flex min-w-0 flex-1 flex-col rounded-xl border border-zinc-200 bg-white">
          {selected ? (
            <>
              <div className="flex items-center justify-between border-b border-zinc-100 p-3">
                <div className="flex min-w-0 items-center gap-2">
                  <ChatAvatar label={selected.userId || selected.threadId} />
                  <span className="truncate text-[13px] font-medium">{selected.userId || selected.threadId}</span>
                  <DeskStateBadge conversation={selected} myEmail={desk.myEmail} nowMs={desk.now} />
                  {(selected.unreadCount || 0) > 0 && (
                    <span className="shrink-0 rounded-full bg-red-500 px-1.5 text-[10px] whitespace-nowrap text-white">
                      未读 {selected.unreadCount}
                    </span>
                  )}
                </div>
                {mineSelected && (
                  <Button variant="outline" className="h-7 px-2.5 text-[11px]" onClick={() => void doRelease()}>
                    释放回 AI
                  </Button>
                )}
              </div>
              {/* P4 台内批驳卡:本会话待批工单内嵌批/驳(spec §2.6) */}
              {desk.pendingTicket && (
                <div
                  className="border-b border-b-amber-100 border-l-4 border-l-amber-400 bg-amber-50/70 px-4 py-2.5"
                  data-testid="desk-ticket-card"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[11px] font-semibold text-amber-700">本会话待批工单</span>
                    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700">
                      {desk.pendingTicket.actionType}
                    </span>
                    {desk.pendingTicket.reason && (
                      <span
                        className="min-w-0 flex-1 truncate text-[11px] text-zinc-500"
                        title={desk.pendingTicket.reason}
                      >
                        {desk.pendingTicket.reason}
                      </span>
                    )}
                    <span className="ml-auto flex shrink-0 gap-1.5">
                      <Button
                        variant="outline"
                        className="h-6 px-2 text-[11px]"
                        data-testid="desk-ticket-approve"
                        disabled={reviewing}
                        onClick={() => void doReview('approve')}
                      >
                        通过
                      </Button>
                      <Button
                        variant="outline"
                        className="h-6 px-2 text-[11px]"
                        data-testid="desk-ticket-reject"
                        disabled={reviewing}
                        onClick={() => setRejectOpen((v) => !v)}
                      >
                        驳回
                      </Button>
                    </span>
                  </div>
                  {rejectOpen && (
                    <div className="mt-2 flex gap-1.5">
                      <input
                        value={rejectReason}
                        onChange={(e) => setRejectReason(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && void doReview('reject')}
                        placeholder="驳回理由(可选)"
                        data-testid="desk-ticket-reason"
                        className="flex-1 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-[12px] outline-none focus:border-zinc-400"
                      />
                      <Button
                        variant="outline"
                        className="h-8 px-3 text-[11px]"
                        data-testid="desk-ticket-confirm-reject"
                        disabled={reviewing}
                        onClick={() => void doReview('reject')}
                      >
                        确认驳回
                      </Button>
                    </div>
                  )}
                </div>
              )}
              <div
                ref={timelineRef}
                onScroll={() => {
                  const el = timelineRef.current;
                  if (el) stickBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
                }}
                className="min-h-0 flex-1 space-y-2.5 overflow-y-auto p-4"
                data-testid="desk-timeline"
              >
                {desk.timeline.map((m, i) => {
                  const day = sameDay(m.timestamp);
                  const prevDay = i > 0 ? sameDay(desk.timeline[i - 1].timestamp) : null;
                  return (
                    <div key={m.id} className="space-y-2.5">
                      {day && day !== prevDay && (
                        <div className="flex items-center gap-2">
                          <span className="h-px flex-1 bg-zinc-100" />
                          <span className="text-[10px] text-zinc-300">
                            {(() => {
                              const d = new Date(
                                m.timestamp.includes('T') ? m.timestamp : m.timestamp.replace(' ', 'T'),
                              );
                              return Number.isNaN(d.getTime()) ? '' : `${d.getMonth() + 1}月${d.getDate()}日`;
                            })()}
                          </span>
                          <span className="h-px flex-1 bg-zinc-100" />
                        </div>
                      )}
                      <TimelineMessage m={m} myEmail={desk.myEmail} />
                    </div>
                  );
                })}
                {desk.timeline.length === 0 && (
                  <div className="flex h-full flex-col items-center justify-center gap-1.5 text-center">
                    {/* biome-ignore lint/a11y/noSvgWithoutTitle: 装饰性空态图标,语义由相邻文案提供 */}
                    <svg aria-hidden viewBox="0 0 24 24" className="h-8 w-8 text-zinc-200" fill="currentColor">
                      <path d="M4 4h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-4 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
                    </svg>
                    <div className="text-[12px] text-zinc-400">暂无消息</div>
                  </div>
                )}
              </div>
              <div className="border-t border-zinc-100 p-3">
                {notice && (
                  <div className="mb-2 rounded-lg bg-red-50 px-2.5 py-1.5 text-[11px] text-red-600">{notice}</div>
                )}
                {/* P4 typing 接线:顾客输入态(服务端 user_typing 透传,2.5s 保持窗) */}
                {desk.peerTyping && (
                  <div className="mb-1.5 flex items-end gap-2" data-testid="desk-typing">
                    <ChatAvatar label={selected.userId || selected.threadId} />
                    <span className="flex items-center gap-2 rounded-2xl rounded-bl-sm bg-zinc-100 px-3 py-2">
                      <TypingDots />
                      <span className="text-[10px] text-zinc-400">对方正在输入…</span>
                    </span>
                  </div>
                )}
                {mineSelected ? (
                  <div className="flex gap-2">
                    <input
                      value={draft}
                      onChange={(e) => {
                        setDraft(e.target.value);
                        if (desk.selectedThreadId) desk.emitTyping(desk.selectedThreadId);
                      }}
                      onKeyDown={(e) => e.key === 'Enter' && void doSend()}
                      placeholder="回复顾客…"
                      className="flex-1 rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-[12px] outline-none transition-colors focus:border-zinc-300 focus:bg-white focus:ring-2 focus:ring-zinc-100"
                    />
                    <Button className="h-9 px-4 text-[12px]" onClick={() => void doSend()}>
                      发送
                    </Button>
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-zinc-200 bg-zinc-50/60 p-3 text-center text-[11px] text-zinc-400">
                    {selected.status === 'human_takeover'
                      ? selected.assignedOperatorId
                        ? '同事接管中,仅接管坐席可回复'
                        : '认领后即可回复顾客'
                      : 'AI 托管中;认领接管后可回复'}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-center">
              {/* biome-ignore lint/a11y/noSvgWithoutTitle: 装饰性空态图标,语义由相邻文案提供 */}
              <svg aria-hidden viewBox="0 0 24 24" className="h-12 w-12 text-zinc-200" fill="currentColor">
                <path d="M4 4h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-4 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
              </svg>
              <div className="text-[13px] text-zinc-500">从左侧选择会话</div>
              <div className="text-[11px] text-zinc-400">排队中的顾客按等待最久置顶,认领后即可回复</div>
            </div>
          )}
        </section>

        {/* 右:坐席上下文栏(P3 五项,spec §2.4)+ 坐席在线态 */}
        <aside className="flex w-80 shrink-0 flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white">
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {desk.context && selected ? (
              <>
                <ContextSection title="客户档案" testId="ctx-section-customer" defaultOpen>
                  <ContextCustomer context={desk.context} />
                </ContextSection>
                <ContextSection
                  title="最近订单"
                  testId="ctx-section-orders"
                  badge={desk.context.recentOrders.length ? String(desk.context.recentOrders.length) : undefined}
                >
                  <ContextOrders context={desk.context} />
                </ContextSection>
                <ContextSection
                  title="售后工单"
                  testId="ctx-section-tickets"
                  badge={
                    desk.context.afterSaleTickets.length ? String(desk.context.afterSaleTickets.length) : undefined
                  }
                >
                  <ContextTickets context={desk.context} />
                </ContextSection>
                <ContextSection title="客户画像" testId="ctx-section-profile">
                  <ContextProfile context={desk.context} />
                </ContextSection>
                <ContextSection
                  title="内部备注"
                  testId="ctx-section-notes"
                  badge={desk.context.notes.length ? String(desk.context.notes.length) : undefined}
                >
                  <ContextNotes
                    context={desk.context}
                    onAdd={(content) => void doAddNote(content)}
                    onRemove={(n) => void doRemoveNote(n.id)}
                  />
                </ContextSection>
              </>
            ) : (
              <div className="py-2 text-center text-[11px] text-zinc-400">
                {selected ? '上下文加载中…' : '选择会话后展示坐席上下文'}
              </div>
            )}

            {/* 坐席在线态(P2 保留,可折叠) */}
            <ContextSection title={`坐席(${desk.agents.length})`} testId="ctx-section-agents" defaultOpen>
              <div className="space-y-1.5">
                {desk.agents.length === 0 && <div className="text-[11px] text-zinc-400">暂无坐席在线</div>}
                {desk.agents.map((a) => (
                  <div key={a.email} className="flex items-center justify-between" data-testid="desk-agent-row">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                          a.dnd ? 'bg-zinc-300' : a.online ? 'bg-emerald-500' : 'bg-zinc-200'
                        }`}
                      />
                      <span className="truncate text-[12px] text-zinc-700">{a.name || a.email}</span>
                    </span>
                    <span
                      className={`shrink-0 rounded-full px-1.5 text-[10px] ${
                        a.dnd
                          ? 'bg-zinc-200 text-zinc-500'
                          : a.online
                            ? 'bg-emerald-100 text-emerald-700'
                            : 'bg-zinc-100 text-zinc-400'
                      }`}
                    >
                      {a.dnd ? '免打扰' : a.online ? '在线' : '离线'}
                    </span>
                  </div>
                ))}
              </div>
              <label className="mt-3 flex cursor-pointer items-center justify-between border-t border-zinc-100 pt-2.5 text-[12px] text-zinc-600">
                免打扰
                <span className="relative inline-flex">
                  <input
                    type="checkbox"
                    data-testid="desk-dnd-toggle"
                    className="peer sr-only"
                    checked={desk.dnd}
                    onChange={(e) => void desk.toggleDnd(e.target.checked)}
                  />
                  <span className="h-5 w-9 rounded-full bg-zinc-200 transition-colors peer-checked:bg-emerald-500" />
                  <span className="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform peer-checked:translate-x-4" />
                </span>
              </label>
            </ContextSection>
          </div>
        </aside>
      </div>
    </div>
  );
}
