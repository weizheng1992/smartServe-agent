import type { DeskNoteItem, LiveDeskContext } from '@/lib/api';
import { fmtMoney } from '@/lib/format';
// 坐席上下文栏渲染件(live-desk-rework P3,spec §2.4 五项):
// 客户档案 / 最近订单 / 售后工单 / 双层画像 / 内部备注,堆叠可折叠。
// 诚实纪律:弱关联未匹配照实呈现(spec 核实结论:聊天身份与商户客户
// 编号现网无桥),严禁用 userId 伪装修配或编造空态数据。
import { useState } from 'react';
import { Button, Input } from 'ui';

/** PG TIMESTAMP naive isoformat(无 Z/时区)→ 本地短格式;Safari 不吃空格分隔。 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

// 金额呈现走 lib/format.fmtMoney 单点;本栏紧凑场景统一传 trim=true(去整 .00)
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
      <Button
        type="button"
        variant="ghost"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center justify-between rounded-lg px-0 py-2 text-left font-normal hover:bg-zinc-50"
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
      </Button>
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
        累计消费 ¥{fmtMoney(c.totalSpent, true)} · {c.orderCount ?? 0} 单
      </div>
    </div>
  );
}

/** 五项之②最近订单(≤5,服务端截断)。客服优化批(2026-10-25)交互化:
 *  行点击开详情 / PAID 行「发货」(canShip = order:ship 显隐,真源服务端)/
 *  「推卡」把订单卡推给顾客(未认领时由调用方拦截提示)。词形「状态 · 金额 ·
 *  时间」为既有 vitest 钉死锚点,保持原始状态码呈现。 */
export function ContextOrders({
  context,
  canShip,
  onOpenOrder,
  onShipOrder,
  onPushOrderCard,
}: {
  context: LiveDeskContext;
  canShip?: boolean;
  onOpenOrder?: (orderId: string) => void;
  onShipOrder?: (orderId: string) => void;
  onPushOrderCard?: (o: { orderId: string; status: string; totalAmount: number; createdAt: string | null }) => void;
}) {
  if (context.recentOrders.length === 0) {
    // 两态可分辨(code-review Spec 轴 2026-10-25):未关联商户客户档案(弱关联
    // 不命中,订单恒查不出)≠ 已关联但确实没有订单 —— 诚实区分,不混为一谈。
    return (
      <EmptyLine
        text={context.customer.matched ? '暂无订单记录' : '会话身份未关联商户客户档案，无法带出订单（关联后自动展示）'}
      />
    );
  }
  return (
    <div className="space-y-1.5">
      {context.recentOrders.map((o) => (
        <div
          key={o.orderId}
          className="rounded-lg border border-zinc-100 px-2 py-1.5 text-[11px] transition-colors hover:border-zinc-200"
          data-testid="ctx-order-row"
        >
          <div className="flex items-center justify-between gap-1">
            <Button
              type="button"
              variant="ghost"
              disabled={!onOpenOrder}
              onClick={() => onOpenOrder?.(o.orderId)}
              className="h-auto min-w-0 flex-1 cursor-pointer justify-start truncate rounded px-0 py-0 text-left font-mono text-[11px] font-normal text-zinc-600 hover:bg-transparent hover:underline"
              title={onOpenOrder ? '查看订单详情' : undefined}
            >
              {o.orderId}
            </Button>
            <span className="shrink-0 text-zinc-400">{fmtTime(o.createdAt)}</span>
          </div>
          <div className="mt-0.5 flex items-center justify-between gap-1">
            <span className="min-w-0 truncate text-zinc-400">
              {o.status} · ¥{fmtMoney(o.totalAmount, true)}
            </span>
            <span className="flex shrink-0 items-center gap-1">
              {canShip && o.status === 'PAID' && onShipOrder && (
                <Button
                  type="button"
                  variant="outline"
                  data-testid="ctx-order-ship"
                  onClick={() => onShipOrder(o.orderId)}
                  className="h-auto cursor-pointer rounded-full border-zinc-300 px-2 py-0 text-[10px] font-normal text-zinc-600 hover:border-zinc-400 hover:bg-zinc-50"
                >
                  发货
                </Button>
              )}
              {onPushOrderCard && (
                <Button
                  type="button"
                  variant="outline"
                  data-testid="ctx-order-push"
                  onClick={() => onPushOrderCard(o)}
                  className="h-auto cursor-pointer rounded-full border-zinc-300 px-2 py-0 text-[10px] font-normal text-zinc-600 hover:border-zinc-400 hover:bg-zinc-50"
                >
                  推卡
                </Button>
              )}
            </span>
          </div>
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
            {t.refundAmount ? ` · ¥${fmtMoney(t.refundAmount, true)}` : ''}
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
        <Input
          value={draft}
          data-testid="ctx-note-input"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="内部备注,仅坐席可见…"
          className="h-auto min-w-0 flex-1 rounded-lg border-zinc-200 px-2 py-1 text-[11px] shadow-none focus-visible:border-zinc-400 focus-visible:ring-0"
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
            <Button
              type="button"
              variant="ghost"
              data-testid="ctx-note-remove"
              onClick={() => onRemove(n)}
              className="h-auto shrink-0 cursor-pointer px-0.5 py-0 text-[10px] font-normal text-zinc-300 hover:text-red-500"
            >
              删除
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
