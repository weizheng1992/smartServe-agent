import { ResultCard } from '@/components/ResultCard';
import { type AskClarifyOption, type AskFrame, type AskRow } from '@/lib/analytics-frames';

export type { AskFrame };
import { getSelection, setSelectionKind } from '@/lib/page-context';
import { useNavigate } from 'react-router';

const ORDER_STATUS: Record<string, string> = {
  PAID: '待发货',
  SHIPPED: '已发货',
  DELIVERED: '已送达',
  REFUNDED: '已退款',
  CANCELLED: '已取消',
  COMPLETED: '已完成',
};

/** 订单行点击 → PageContext 契约:并入内存选中集合并跳订单管理(勾选态带过去;
 *  严禁 localStorage——残留勾选曾两次静默污染查询,merchant-admin.md §1.3)。 */
function useJumpToOrder() {
  const navigate = useNavigate();
  return (orderId: string) => {
    const ids = new Set([...(getSelection().order || []), orderId]);
    setSelectionKind('order', [...ids].slice(0, 100));
    navigate('/orders');
  };
}

/** 问答流水:用户气泡 / 折线卡 / 表格卡 / 客户订单列表卡 / clarify 反问 / 诚实拒绝。 */
export function AskTranscript({ frames, onAsk }: { frames: AskFrame[]; onAsk: (q: string) => void }) {
  const jumpToOrder = useJumpToOrder();

  return (
    <>
      {frames
        .filter((f) => f.event !== 'start')
        .map((f, i) => (
          /* biome-ignore lint/suspicious/noArrayIndexKey: AskFrame 无业务 id,append-only 对话流不重排 */
          <div key={i} className={f.event === 'user' ? 'flex justify-end' : ''}>
            {f.event === 'user' ? (
              <div className="rounded-xl bg-zinc-900 px-4 py-2 text-sm text-white">{f.data.message}</div>
            ) : f.event === 'result' && f.data.metric === 'customer_orders' && Array.isArray(f.data.rows) ? (
              // 行级「在订单中查看」跳转是 analytics 全屏问答页独有的交互特例
              // (静态渲染与 ResultCard 同口径);其余 result 帧一律走唯一渲染缝。
              <CustomerOrdersCard rows={f.data.rows} caliber={f.data.caliber ?? ''} onJump={jumpToOrder} />
            ) : f.event === 'result' ? (
              // 唯一渲染缝(merchant-admin.md §1.4):折线/条形/诚实降级/文本卡
              // 全在共享 ResultCard —— 折线值列 Number.isFinite 护栏(2026-09-25
              // 此旁路自绘表格曾复现已修复的 NaN 网线事故)、排行自动条形、
              // 「数据点不足」降级均与悬浮面板/看板/报告四处同形。
              <ResultCard data={f.data} />
            ) : (
              <div className="rounded-xl border border-zinc-200 bg-white p-4 text-sm">
                {f.data.message || f.event}
                {f.event === 'clarify' && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(f.data.options || []).map((o: AskClarifyOption, j: number) => (
                      <button
                        /* biome-ignore lint/suspicious/noArrayIndexKey: clarify 选项无 id,静态文案按钮不重排 */
                        key={j}
                        type="button"
                        className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs"
                        onClick={() =>
                          onAsk(
                            f.data.clarifyKind === 'entity'
                              ? f.data.originalQuestion
                                ? `${f.data.originalQuestion}(${o.label})`
                                : o.label
                              : `按${o.label}的商品排行`,
                          )
                        }
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

function orderCell(v: unknown): string {
  return v === null || v === undefined ? '' : String(v);
}

/** 金额口径与订单管理页一致(toFixed(2));缺值/坏值诚实「—」—— 注意
 *  Number(null) === 0,必须先挡空值,否则缺金额渲染成假 ¥0.00。 */
function formatAmount(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(2) : '—';
}

/** 客户订单列表卡:行级「在订单中查看」跳订单管理并勾选。 */
function CustomerOrdersCard({
  rows,
  caliber,
  onJump,
}: { rows: AskRow[]; caliber: string; onJump: (id: string) => void }) {
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
              <tr key={orderCell(r.order_id) || k} className="border-b border-zinc-50">
                <td className="px-4 py-2 font-mono">{orderCell(r.order_id)}</td>
                <td className="px-4 py-2">{ORDER_STATUS[orderCell(r.status)] || orderCell(r.status)}</td>
                <td className="px-4 py-2">¥{formatAmount(r.total_amount)}</td>
                <td className="px-4 py-2 text-zinc-500">{orderCell(r.created_at)}</td>
                <td className="px-4 py-2 text-right">
                  <button
                    type="button"
                    className="cursor-pointer text-xs text-blue-600 hover:text-blue-700"
                    onClick={() => onJump(orderCell(r.order_id))}
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
