import { useWorkbench, type WorkbenchTab } from "../workbench";

const TABS: Array<{ key: WorkbenchTab; label: string; tone: 'emerald' | 'amber' | 'blue' }> = [
  { key: 'orders', label: '📋 订单中心', tone: 'emerald' },
  { key: 'approvals', label: '🛡️ 待办审核 (HITL)', tone: 'amber' },
  { key: 'live_desk', label: '💬 在线客服工作台', tone: 'blue' },
  { key: 'spus', label: '🏷️ SPU 商品库', tone: 'emerald' },
  { key: 'skus', label: '📦 SKU 规格库存', tone: 'emerald' },
  { key: 'spi_logs', label: '🔌 SPI 开放审计流水', tone: 'emerald' },
];

const TONE_BADGE: Record<'emerald' | 'amber' | 'blue', { on: string; off: string }> = {
  emerald: { on: 'border-emerald-600 text-emerald-700', off: 'bg-slate-100 text-slate-600' },
  amber: { on: 'border-amber-500 text-amber-700', off: 'bg-slate-100 text-slate-600' },
  blue: { on: 'border-blue-600 text-blue-700', off: 'bg-blue-100 text-blue-700' },
};

/** 六 tab 导航:徽标为该域当前条数(审批有待办时脉动提示)。 */
export function TabNav() {
  const { activeTab, setActiveTab, orders, spus, skus, conversations, auditLogs, pendingApprovalsCount } = useWorkbench();

  const counts: Record<WorkbenchTab, { n: number; highlight?: boolean }> = {
    orders: { n: orders.length },
    approvals: { n: pendingApprovalsCount, highlight: pendingApprovalsCount > 0 },
    live_desk: { n: conversations.length, highlight: true },
    spus: { n: spus.length },
    skus: { n: skus.length },
    spi_logs: { n: auditLogs.length, highlight: true },
  };

  return (
    <div className="flex border-b border-slate-200 bg-white rounded-t-xl px-4 pt-3 gap-6 shadow-2xs overflow-x-auto">
      {TABS.map((t) => {
        const c = counts[t.key];
        const badge = t.key === 'approvals' && c.highlight
          ? 'bg-amber-100 text-amber-800 animate-pulse font-bold'
          : TONE_BADGE[t.tone].off;
        return (
          <button
            key={t.key}
            type="button"
            onClick={() => setActiveTab(t.key)}
            className={`pb-3 text-sm font-semibold flex items-center space-x-2 border-b-2 transition whitespace-nowrap cursor-pointer ${
              activeTab === t.key
                ? TONE_BADGE[t.tone].on
                : 'border-transparent text-slate-600 hover:text-slate-900'
            }`}
          >
            <span>{t.label}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full ${badge}`}>{c.n}</span>
          </button>
        );
      })}
    </div>
  );
}
