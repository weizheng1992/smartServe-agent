import { FeedbackButtons } from '@/components/FeedbackButtons';
import { ResultCard } from '@/components/ResultCard';
import {
  DenseTable,
  DenseTableBody,
  DenseTableCell,
  DenseTableHead,
  DenseTableHeader,
  DenseTableRow,
} from '@/components/dense-table';
import type { AskClarifyOption, AskRow, FeedbackVerdict, SessionFrame } from '@/lib/analytics-frames';
import { clarifyAskQuestion, isFeedbackTail } from '@/lib/ask-session';
import { fmtMoney, orderStatusMeta } from '@/lib/format';
import { getSelection, setSelectionKind } from '@/lib/page-context';
import { useNavigate } from 'react-router';
import { Button } from 'ui';

const ORDER_STATUS = (status: string) => orderStatusMeta(status).label;

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

/** 问答流水(渲染 adapter):用户气泡 / 折线卡 / 表格卡 / 客户订单列表卡 /
 *  clarify 反问 / 诚实拒绝。会话状态(帧机/断线恢复/反馈闩锁)在 lib/ask-session
 *  单点 —— 本组件只渲染:rated 读帧标注、反馈与恢复经回调打回会话
 *  (onResume → session.resume(f.id),onRate → session.rate(f.id, verdict, note));
 *  组尾判定与 clarify 追问句组装走共享纯函数,严禁组件内重抄。
 *  heartbeat/start 在会话摄入期已过滤,不入对话流。 */
export function AskTranscript({
  frames,
  onAsk,
  onResume,
  onRate,
  rateBusyId = null,
  busy = false,
}: {
  frames: SessionFrame[];
  onAsk: (q: string) => void;
  onResume?: (frame: SessionFrame) => void;
  onRate?: (frame: SessionFrame, verdict: FeedbackVerdict, note?: string) => void;
  rateBusyId?: number | null;
  busy?: boolean;
}) {
  const jumpToOrder = useJumpToOrder();

  return (
    <>
      {frames.map((f, i) => (
        <div key={f.id} className={f.event === 'user' ? 'flex justify-end' : ''}>
          {f.event === 'user' ? (
            <div className="rounded-xl bg-zinc-900 px-4 py-2 text-sm text-white">{f.data.message}</div>
          ) : f.event === 'result' && f.data.metric === 'customer_orders' && Array.isArray(f.data.rows) ? (
            // 行级「在订单中查看」跳转是 analytics 全屏问答页独有的交互特例
            // (静态渲染与 ResultCard 同口径);其余 result 帧一律走唯一渲染缝。
            <>
              <CustomerOrdersCard rows={f.data.rows} caliber={f.data.caliber ?? ''} onJump={jumpToOrder} />
              {onRate && isFeedbackTail(frames, i) ? (
                <FeedbackButtons
                  rated={f.rated}
                  busy={rateBusyId === f.id}
                  onSubmit={(verdict, note) => onRate(f, verdict, note)}
                />
              ) : null}
            </>
          ) : f.event === 'result' ? (
            // 唯一渲染缝(merchant-admin.md §1.4):折线/条形/诚实降级/文本卡
            // 全在共享 ResultCard —— 折线值列 Number.isFinite 护栏(2026-09-25
            // 此旁路自绘表格曾复现已修复的 NaN 网线事故)、排行自动条形、
            // 「数据点不足」降级均与悬浮面板/看板/报告四处同形。
            <>
              <ResultCard data={f.data} />
              {onRate && isFeedbackTail(frames, i) ? (
                <FeedbackButtons
                  rated={f.rated}
                  busy={rateBusyId === f.id}
                  onSubmit={(verdict, note) => onRate(f, verdict, note)}
                />
              ) : null}
            </>
          ) : (
            <div className="rounded-xl border border-zinc-200 bg-white p-4 text-sm">
              {/* clarify 帧正文在 question(引擎 Clarify.to_frame 无 message 键;
                  读 message 曾把全屏页 clarify 渲染成字面量 "clarify") */}
              {f.event === 'clarify' ? (f.data.question ?? '') : f.data.message || f.event}
              {f.event === 'clarify' && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {(f.data.options || []).map((o: AskClarifyOption) => (
                    <Button
                      key={o.label}
                      type="button"
                      variant="outline"
                      className="rounded-lg border-zinc-300 px-3 py-1.5 text-xs font-normal shadow-none"
                      onClick={() => onAsk(clarifyAskQuestion(f.data, o))}
                    >
                      {o.label}
                    </Button>
                  ))}
                </div>
              )}
              {f.data.caliber ? <div className="mt-1 text-[11px] text-zinc-400">口径:{f.data.caliber}</div> : null}
              {onResume && f.data.resume ? (
                <div className="mt-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={busy}
                    className="rounded-lg border-zinc-300 px-3 py-1.5 text-xs font-normal shadow-none hover:border-zinc-900 disabled:opacity-60"
                    onClick={() => onResume(f)}
                  >
                    恢复结果
                  </Button>
                </div>
              ) : null}
              {f.event === 'unsupported' && onRate && isFeedbackTail(frames, i) ? (
                <FeedbackButtons
                  allowUp={false}
                  rated={f.rated}
                  busy={rateBusyId === f.id}
                  onSubmit={(verdict, note) => onRate(f, verdict, note)}
                />
              ) : null}
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
        <DenseTable>
          <DenseTableHeader>
            <DenseTableRow className="border-b border-zinc-100 hover:bg-transparent">
              <DenseTableHead>订单号</DenseTableHead>
              <DenseTableHead>状态</DenseTableHead>
              <DenseTableHead>金额</DenseTableHead>
              <DenseTableHead>下单时间</DenseTableHead>
              <DenseTableHead />
            </DenseTableRow>
          </DenseTableHeader>
          <DenseTableBody>
            {rows.map((r, k) => (
              <DenseTableRow key={orderCell(r.order_id) || k}>
                <DenseTableCell className="font-mono">{orderCell(r.order_id)}</DenseTableCell>
                <DenseTableCell>{ORDER_STATUS(orderCell(r.status))}</DenseTableCell>
                <DenseTableCell>¥{fmtMoney(r.total_amount)}</DenseTableCell>
                <DenseTableCell className="text-zinc-500">{orderCell(r.created_at)}</DenseTableCell>
                <DenseTableCell className="text-right">
                  <Button
                    type="button"
                    variant="link"
                    className="h-auto cursor-pointer p-0 text-xs font-normal text-blue-600 hover:text-blue-700"
                    onClick={() => onJump(orderCell(r.order_id))}
                  >
                    在订单中查看
                  </Button>
                </DenseTableCell>
              </DenseTableRow>
            ))}
          </DenseTableBody>
        </DenseTable>
      )}
      <div className="border-t border-zinc-100 px-4 py-1.5 text-[11px] text-zinc-400">口径:{caliber}</div>
    </div>
  );
}
