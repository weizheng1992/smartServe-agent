import type { DeskNoteItem, LiveDeskContext } from '@/lib/api';
// 坐席上下文栏渲染件(live-desk-rework P3,spec §2.4 五项):
// 客户档案 / 最近订单 / 售后工单 / 双层画像 / 内部备注,堆叠可折叠。
// 诚实纪律:弱关联未匹配照实呈现(spec 核实结论:聊天身份与商户客户
// 编号现网无桥),严禁用 userId 伪装修配或编造空态数据。
import { useState } from 'react';
import { Button } from 'ui';

/** PG TIMESTAMP naive isoformat(无 Z/时区)→ 本地短格式;Safari 不吃空格分隔。 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

const fmtMoney = (n: number) => `¥${Number(n).toFixed(2).replace(/\.00$/, '')}`;

export function ContextSection({
  title,
  testId,
  defaultOpen = false,
  badge,
  children,
}: {
  title: string;
  testId: string;
  defaultOpen?: boolean;
  badge?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-zinc-100 last:border-b-0" data-testid={testId}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center justify-between rounded-lg py-2 text-left transition-colors hover:bg-zinc-50"
      >
        <span className="flex items-center gap-1.5 text-[12px] font-semibold text-zinc-700">
          {/* biome-ignore lint/a11y/noSvgWithoutTitle: 装饰性折叠指示箭头,开合态由 aria-expanded 表达 */}
          <svg
            aria-hidden
            viewBox="0 0 16 16"
            className={`h-3 w-3 shrink-0 text-zinc-400 transition-transform ${open ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {title}
          {badge && (
            <span className="rounded-full bg-zinc-100 px-1.5 text-[10px] font-normal text-zinc-500">{badge}</span>
          )}
        </span>
      </button>
      {open && <div className="pb-2.5">{children}</div>}
    </div>
  );
}

const EmptyLine = ({ text }: { text: string }) => <div className="text-[11px] leading-5 text-zinc-400">{text}</div>;

/** 五项之①客户档案:弱关联命中显档案,未匹配显诚实空态。 */
export function ContextCustomer({ context }: { context: LiveDeskContext }) {
  const c = context.customer;
  if (!c.matched) {
    return (
      <div data-testid="ctx-customer-unmatched">
        <EmptyLine text="未匹配到商户客户档案(聊天身份与商户客户编号暂无关联)" />
      </div>
    );
  }
  return (
    <div className="space-y-1 text-[11px] leading-5" data-testid="ctx-customer-matched">
      <div className="flex items-center gap-1.5">
        <span className="text-[12px] font-medium text-zinc-800">{c.name}</span>
        {c.memberLevel && <span className="rounded bg-amber-50 px-1 text-[10px] text-amber-700">{c.memberLevel}</span>}
        {(c.tags || []).map((t) => (
          <span key={t} className="rounded bg-zinc-100 px-1 text-[10px] text-zinc-500">
            {t}
          </span>
        ))}
      </div>
      <div className="text-zinc-500">手机 {c.phoneMasked || '—'}</div>
      {c.email ? <div className="text-zinc-500">{c.email}</div> : null}
      <div className="text-zinc-500">
        累计消费 {fmtMoney(c.totalSpent || 0)} · {c.orderCount ?? 0} 单
      </div>
    </div>
  );
}

/** 五项之②最近订单(≤5,服务端截断)。 */
export function ContextOrders({ context }: { context: LiveDeskContext }) {
  if (context.recentOrders.length === 0) return <EmptyLine text="暂无订单记录" />;
  return (
    <div className="space-y-1.5">
      {context.recentOrders.map((o) => (
        <div key={o.orderId} className="flex items-center justify-between text-[11px]" data-testid="ctx-order-row">
          <span className="min-w-0 truncate text-zinc-600">{o.orderId}</span>
          <span className="ml-2 shrink-0 text-zinc-400">
            {o.status} · {fmtMoney(o.totalAmount)} · {fmtTime(o.createdAt)}
          </span>
        </div>
      ))}
    </div>
  );
}

/** 五项之③售后中工单(终态不出现,服务端过滤)。 */
export function ContextTickets({ context }: { context: LiveDeskContext }) {
  if (context.afterSaleTickets.length === 0) return <EmptyLine text="暂无售后中工单" />;
  return (
    <div className="space-y-1.5">
      {context.afterSaleTickets.map((t) => (
        <div key={t.id} className="text-[11px] leading-5" data-testid="ctx-ticket-row">
          <span className="text-zinc-600">{t.type === 'refund' ? '退款' : t.type}</span>
          <span className="text-zinc-400"> · {t.reason}</span>
          <span className="float-right text-zinc-400">
            {t.status}
            {t.refundAmount ? ` · ${fmtMoney(t.refundAmount)}` : ''}
          </span>
        </div>
      ))}
    </div>
  );
}

/** 五项之④双层画像:global 全平台 / tenant 本店 分栏,严禁合并。 */
export function ContextProfile({ context }: { context: LiveDeskContext }) {
  const { global: g, tenant: t } = context.profile;
  if (g.length === 0 && t.length === 0) return <EmptyLine text="暂无画像事实" />;
  return (
    <div className="space-y-2">
      <div data-testid="ctx-profile-global">
        <div className="text-[10px] text-zinc-400">全局通用</div>
        {g.length === 0 ? (
          <EmptyLine text="无" />
        ) : (
          g.map((f) => (
            <div key={f} className="text-[11px] leading-5 text-zinc-600">
              · {f}
            </div>
          ))
        )}
      </div>
      <div data-testid="ctx-profile-tenant">
        <div className="text-[10px] text-zinc-400">本店专属</div>
        {t.length === 0 ? (
          <EmptyLine text="无" />
        ) : (
          t.map((f) => (
            <div key={f} className="text-[11px] leading-5 text-zinc-600">
              · {f}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/** 五项之⑤内部备注:仅坐席可见(thread_notes,顾客链路物理触不到)。 */
export function ContextNotes({
  context,
  onAdd,
  onRemove,
}: {
  context: LiveDeskContext;
  onAdd: (content: string) => void;
  onRemove: (note: DeskNoteItem) => void;
}) {
  const [draft, setDraft] = useState('');
  const submit = () => {
    const content = draft.trim();
    if (!content) return;
    setDraft('');
    onAdd(content);
  };
  return (
    <div>
      <div className="flex gap-1.5">
        <input
          value={draft}
          data-testid="ctx-note-input"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="内部备注,仅坐席可见…"
          className="min-w-0 flex-1 rounded-lg border border-zinc-200 px-2 py-1 text-[11px] outline-none focus:border-zinc-400"
        />
        <Button className="h-7 shrink-0 px-2.5 text-[11px]" data-testid="ctx-note-add" onClick={submit}>
          添加
        </Button>
      </div>
      <div className="mt-2 space-y-1.5">
        {context.notes.length === 0 && <EmptyLine text="暂无备注" />}
        {context.notes.map((n) => (
          <div key={n.id} className="group flex items-start justify-between gap-1.5" data-testid="ctx-note-row">
            <div className="min-w-0">
              <div className="whitespace-pre-wrap break-words text-[11px] leading-5 text-zinc-700">{n.content}</div>
              <div className="text-[10px] text-zinc-400">
                {n.authorEmail} · {fmtTime(n.createdAt)}
              </div>
            </div>
            <button
              type="button"
              data-testid="ctx-note-remove"
              onClick={() => onRemove(n)}
              className="shrink-0 cursor-pointer text-[10px] text-zinc-300 hover:text-red-500"
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
