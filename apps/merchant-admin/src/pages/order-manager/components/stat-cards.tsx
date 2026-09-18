import { useWorkbench } from "../workbench";

/** 顶部四栏核心指标看板:点击卡片即快捷跳转到对应 tab。 */
export function StatCards() {
  const {
    activeTab, setActiveTab,
    orders, conversations, spus, skus,
    paidOrdersCount, shippedOrdersCount, pendingApprovalsCount, lowStockCount,
  } = useWorkbench();

  const takeoverCount = conversations.filter((c) => c.status === 'human_takeover').length;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: 看板卡片点击为快捷导航,键盘路径由顶部 Tab 承担 */}
      <div
        onClick={() => setActiveTab('orders')}
        className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-emerald-400 transition"
      >
        <div>
          <div className="text-xs text-slate-500 font-medium">累计订单总数</div>
          <div className="text-2xl font-bold text-slate-900 mt-1">{orders.length} 笔</div>
          <div className="text-[11px] text-slate-400 mt-1 flex gap-2">
            <span>待发: {paidOrdersCount}</span>
            <span>已发: {shippedOrdersCount}</span>
          </div>
        </div>
        <div className="text-3xl text-slate-300">📋</div>
      </div>
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: 看板卡片点击为快捷导航,键盘路径由顶部 Tab 承担 */}
      <div
        onClick={() => setActiveTab('approvals')}
        className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-amber-400 transition"
      >
        <div>
          <div className="text-xs text-slate-500 font-medium flex items-center space-x-1">
            <span>待人工审核工单</span>
            {pendingApprovalsCount > 0 && <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />}
          </div>
          <div
            className={`text-2xl font-bold mt-1 ${pendingApprovalsCount > 0 ? 'text-amber-600' : 'text-slate-900'}`}
          >
            {pendingApprovalsCount} 笔
          </div>
          <div className="text-[11px] text-amber-600/80 mt-1">
            {pendingApprovalsCount > 0 ? '需及时核决以放行流程' : '大盘运转平稳'}
          </div>
        </div>
        <div className="text-3xl text-amber-300">🛡️</div>
      </div>
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: 看板卡片点击为快捷导航,键盘路径由顶部 Tab 承担 */}
      <div
        onClick={() => setActiveTab('live_desk')}
        className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-blue-400 transition"
      >
        <div>
          <div className="text-xs text-slate-500 font-medium">活跃在线会话</div>
          <div className="text-2xl font-bold text-blue-600 mt-1">{conversations.length} 组</div>
          <div className="text-[11px] text-blue-500/80 mt-1">
            接管: {takeoverCount} · 托管: {conversations.length - takeoverCount}
          </div>
        </div>
        <div className="text-3xl text-blue-300">💬</div>
      </div>
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: 看板卡片点击为快捷导航,键盘路径由顶部 Tab 承担 */}
      <div
        onClick={() => setActiveTab('skus')}
        className="bg-white p-5 rounded-xl border border-slate-200 shadow-2xs flex items-center justify-between cursor-pointer hover:border-purple-400 transition"
      >
        <div>
          <div className="text-xs text-slate-500 font-medium flex items-center gap-1">
            <span>SKU 库存监控</span>
            {lowStockCount > 0 && (
              <span className="text-[10px] bg-rose-100 text-rose-700 px-1.5 py-0.2 rounded font-bold">
                {lowStockCount} 低库存
              </span>
            )}
          </div>
          <div className="text-2xl font-bold text-slate-900 mt-1">{skus.length} 款</div>
          <div className="text-[11px] text-slate-400 mt-1">SPU 库: {spus.length} 款商品</div>
        </div>
        <div className="text-3xl text-purple-300">📦</div>
      </div>
    </div>
  );
}
