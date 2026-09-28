import { useMemo, useState } from 'react';
// 坐席台独立页(live-desk-rework P2/P3):三栏 —— 左会话池(排队等待最久置顶)/
// 中时间线(认领后回复)/ 右坐席上下文栏(五项,spec §2.4)+ 坐席在线态。
// 旧 /live-desk tab(OrderWorkbench)并存不动作回退面;本页是 spec §3
// P2/P3 的正式坐席工作台。
import { Button } from 'ui';
import {
  ContextCustomer,
  ContextNotes,
  ContextOrders,
  ContextProfile,
  ContextSection,
  ContextTickets,
} from './live-desk-context-parts';
import { type DeskTab, filterConversations, sortQueueFirst } from './live-desk-model';
import { ConversationRow, DeskStateBadge } from './live-desk-parts';
import { useLiveDesk } from './use-live-desk';

const TABS: Array<{ key: DeskTab; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'queuing', label: '排队中' },
  { key: 'mine', label: '我的' },
];

export default function LiveDeskPage() {
  const desk = useLiveDesk();
  const [tab, setTab] = useState<DeskTab>('all');
  const [keyword, setKeyword] = useState('');
  const [draft, setDraft] = useState('');
  const [claimingId, setClaimingId] = useState<string | null>(null);
  const [notice, setNotice] = useState('');

  const visible = useMemo(
    () => sortQueueFirst(filterConversations(desk.conversations, desk.myEmail, tab, keyword)),
    [desk.conversations, desk.myEmail, tab, keyword],
  );
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
    <div className="flex h-full min-h-0 gap-4">
      {/* 左:会话池 */}
      <aside className="flex w-80 shrink-0 flex-col rounded-xl border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 p-3">
          <div className="flex items-center justify-between">
            <div className="text-[13px] font-semibold">会话池</div>
            <span className={`text-[11px] ${desk.connected ? 'text-emerald-600' : 'text-zinc-400'}`}>
              {desk.connected ? '● 实时已连接' : '○ 未连接'}
            </span>
          </div>
          <div className="mt-2 flex gap-1">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                data-testid={`desk-tab-${t.key}`}
                onClick={() => setTab(t.key)}
                className={`cursor-pointer rounded-full px-2.5 py-1 text-[11px] ${
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
            className="mt-2 w-full rounded-lg border border-zinc-200 px-2.5 py-1.5 text-[12px] outline-none focus:border-zinc-400"
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
                <span className="truncate text-[13px] font-medium">{selected.userId || selected.threadId}</span>
                <DeskStateBadge conversation={selected} myEmail={desk.myEmail} nowMs={desk.now} />
                {(selected.unreadCount || 0) > 0 && (
                  <span className="rounded-full bg-red-500 px-1.5 text-[10px] text-white">
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
            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4" data-testid="desk-timeline">
              {desk.timeline.map((m) => (
                <div
                  key={m.id}
                  className={`max-w-[70%] rounded-lg px-3 py-2 text-[12px] ${
                    m.role === 'operator'
                      ? 'ml-auto bg-emerald-600 text-white'
                      : m.role === 'user'
                        ? 'bg-zinc-100 text-zinc-800'
                        : 'mx-auto bg-amber-50 text-amber-700'
                  }`}
                >
                  {m.role === 'system' && <div className="mb-0.5 text-[10px] opacity-70">系统</div>}
                  {m.role === 'operator' && m.operatorInfo && (
                    <div className="mb-0.5 text-[10px] opacity-70">{m.operatorInfo.operatorName}</div>
                  )}
                  {m.content}
                </div>
              ))}
              {desk.timeline.length === 0 && <div className="p-6 text-center text-[12px] text-zinc-400">暂无消息</div>}
            </div>
            <div className="border-t border-zinc-100 p-3">
              {notice && <div className="mb-2 text-[11px] text-red-500">{notice}</div>}
              {mineSelected ? (
                <div className="flex gap-2">
                  <input
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && void doSend()}
                    placeholder="回复顾客…"
                    className="flex-1 rounded-lg border border-zinc-200 px-3 py-2 text-[12px] outline-none focus:border-zinc-400"
                  />
                  <Button className="h-9 px-4 text-[12px]" onClick={() => void doSend()}>
                    发送
                  </Button>
                </div>
              ) : (
                <div className="rounded-lg bg-zinc-50 p-2.5 text-center text-[11px] text-zinc-400">
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
          <div className="flex flex-1 items-center justify-center text-[13px] text-zinc-400">
            从左侧选择会话;排队中的顾客等待最久置顶
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
                badge={desk.context.afterSaleTickets.length ? String(desk.context.afterSaleTickets.length) : undefined}
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
                  <span className="truncate text-[12px] text-zinc-700">{a.name || a.email}</span>
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
            <label className="mt-3 flex cursor-pointer items-center justify-between border-t border-zinc-100 pt-2 text-[12px] text-zinc-600">
              免打扰
              <input
                type="checkbox"
                data-testid="desk-dnd-toggle"
                checked={desk.dnd}
                onChange={(e) => void desk.toggleDnd(e.target.checked)}
                className="h-4 w-4"
              />
            </label>
          </ContextSection>
        </div>
      </aside>
    </div>
  );
}
