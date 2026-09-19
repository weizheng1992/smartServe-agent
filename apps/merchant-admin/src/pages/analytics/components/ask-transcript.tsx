import { useNavigate } from 'react-router';
import { LineChart } from '@/components/LineChart';

export type AskFrame = { event: string; data: any };

const ORDER_STATUS: Record<string, string> = {
  PAID: '待发货', SHIPPED: '已发货', DELIVERED: '已送达', REFUNDED: '已退款', CANCELLED: '已取消', COMPLETED: '已完成',
};

/** 订单行点击 → PageContext 契约:写入选中集合并跳订单管理(勾选态带过去)。 */
function useJumpToOrder() {
  const navigate = useNavigate();
  return (orderId: string) => {
    try {
      const prev = JSON.parse(localStorage.getItem('merchant-admin.selection') || '[]') as string[];
      localStorage.setItem('merchant-admin.selection', JSON.stringify([...new Set([orderId, ...prev])].slice(0, 100)));
    } catch { /* 存储不可用时仅跳转 */ }
    navigate('/orders');
  };
}

/** 问答流水:用户气泡 / 折线卡 / 表格卡 / 客户订单列表卡 / clarify 反问 / 诚实拒绝。 */
export function AskTranscript({ frames, onAsk }: { frames: AskFrame[]; onAsk: (q: string) => void }) {
  const jumpToOrder = useJumpToOrder();

  return (
    <>
      {frames.filter((f) => f.event !== 'start').map((f, i) => (
        <div key={i} className={f.event === 'user' ? 'flex justify-end' : ''}>
          {f.event === 'user' ? (
            <div className="rounded-xl bg-zinc-900 px-4 py-2 text-sm text-white">{f.data.message}</div>
          ) : f.event === 'result' && f.data.metric === 'customer_orders' && Array.isArray(f.data.rows) ? (
            <CustomerOrdersCard rows={f.data.rows} caliber={f.data.caliber} onJump={jumpToOrder} />
          ) : f.event === 'result' && f.data.chart === 'line' && Array.isArray(f.data.rows) && f.data.rows.length >= 2 ? (
            <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
              <div className="border-b border-zinc-100 px-4 py-2 text-xs font-medium text-zinc-500">{f.data.metric} · {f.data.unit}</div>
              <LineChart points={f.data.rows.map((r: any) => ({ label: String(Object.values(r)[0]), value: Number(Object.values(r)[1]) }))} unit={f.data.unit} />
              <div className="border-t border-zinc-100 px-4 py-1.5 text-[11px] text-zinc-400">口径:{f.data.caliber}</div>
            </div>
          ) : f.event === 'result' ? (
            <div className="space-y-2">
              {(f.data.cards || []).map((card: any, j: number) =>
                card.type === 'table' ? (
                  <div key={j} className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
                    <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-2">
                      <span className="text-xs font-medium text-zinc-500">{card.title}</span>
                    </div>
                    <table className="w-full text-[13px]">
                      <thead>
                        <tr className="border-b border-zinc-100 text-left text-zinc-400">
                          {card.columns.map((c: any) => <th key={c.key} className="px-4 py-2 font-medium">{c.label}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {card.rows.map((r: any, k: number) => (
                          <tr key={k} className="border-b border-zinc-50">
                            {card.columns.map((c: any) => <td key={c.key} className="px-4 py-2">{String(r[c.key])}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="border-t border-zinc-100 px-4 py-1.5 text-[11px] text-zinc-400">口径:{card.caliber}</div>
                  </div>
                ) : (
                  <div key={j} className="rounded-xl border border-zinc-200 bg-white p-4 text-sm">{card.text}</div>
                ),
              )}
            </div>
          ) : (
            <div className="rounded-xl border border-zinc-200 bg-white p-4 text-sm">
              {f.data.message || f.event}
              {f.event === 'clarify' && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {(f.data.options || []).map((o: any, j: number) => (
                    <button
                      key={j}
                      type="button"
                      className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs"
                      onClick={() => onAsk(f.data.clarifyKind === 'entity' ? o.label : `按${o.label}的商品排行`)}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
              )}
              {f.data.caliber ? <div className="mt-1 text-[11px] text-zinc-400">口径:{f.data.caliber}</div> : null}
            </div>
          )}
        </div>
      ))}
    </>
  );
}

/** 客户订单列表卡:行级「在订单中查看」跳订单管理并勾选。 */
function CustomerOrdersCard({ rows, caliber, onJump }: { rows: any[]; caliber: string; onJump: (id: string) => void }) {
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <div className="border-b border-zinc-100 px-4 py-2 text-xs font-medium text-zinc-500">客户订单</div>
      {rows.length === 0 ? (
        <div className="px-4 py-4 text-sm text-zinc-400">该客户名下暂无订单(诚实空)。</div>
      ) : (
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-zinc-100 text-left text-zinc-400">
              <th className="px-4 py-2 font-medium">订单号</th>
              <th className="px-4 py-2 font-medium">状态</th>
              <th className="px-4 py-2 font-medium">金额</th>
              <th className="px-4 py-2 font-medium">下单时间</th>
              <th className="px-4 py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, k) => (
              <tr key={r.order_id || k} className="border-b border-zinc-50">
                <td className="px-4 py-2 font-mono">{r.order_id}</td>
                <td className="px-4 py-2">{ORDER_STATUS[r.status] || r.status}</td>
                <td className="px-4 py-2">¥{Number(r.total_amount).toLocaleString()}</td>
                <td className="px-4 py-2 text-zinc-500">{r.created_at}</td>
                <td className="px-4 py-2 text-right">
                  <button
                    type="button"
                    className="cursor-pointer text-xs text-blue-600 hover:text-blue-700"
                    onClick={() => onJump(r.order_id)}
                  >
                    在订单中查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="border-t border-zinc-100 px-4 py-1.5 text-[11px] text-zinc-400">口径:{caliber}</div>
    </div>
  );
}
