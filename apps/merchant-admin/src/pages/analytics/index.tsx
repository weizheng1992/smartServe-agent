import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from 'ui';
import { LineChart } from '@/components/LineChart';
import { api } from '@/lib/api';

const CAPSULES = ['本月销量 Top10', '卖得最差的商品', '差评最多的 SKU', '近 30 天退款率', '售后工单概况', '客服负载概况'];

// 全屏工作台(16 号):多轮深聊/多卡;与悬浮共享同一后端 ask。
export default function AnalyticsPage({ role }: { role: string }) {
  const [frames, setFrames] = useState<Array<{ event: string; data: any }>>([]);
  const [busy, setBusy] = useState(false);
  const [reportMsg, setReportMsg] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  const ask = useCallback(async (question: string) => {
    if (!question.trim() || busy) return;
    setBusy(true);
    setFrames((p) => [...p, { event: 'user', data: { message: question } }]);
    try {
      const result = await api.ask(question);
      setFrames((p) => [...p, ...result]);
    } catch (err) {
      setFrames((p) => [...p, { event: 'error', data: { message: String(err) } }]);
    }
    setBusy(false);
    requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 1e9 }));
  }, [busy]);

  useEffect(() => { void ask('本月销量 Top10'); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function genReport() {
    setReportMsg('生成中…');
    try {
      const r = await api.reports.create();
      setReportMsg(`✓ ${r.title} 已生成(我的报告可查)`);
    } catch (err) {
      setReportMsg(`生成失败:${String(err)}`);
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col">
      <div className="flex flex-wrap gap-2 pb-4">
        {CAPSULES.map((c) => (
          <button key={c} className="rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-xs hover:border-zinc-900" onClick={() => void ask(c)}>
            {c}
          </button>
        ))}
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        {frames.filter((f) => f.event !== 'start').map((f, i) => (
          <div key={i} className={f.event === 'user' ? 'flex justify-end' : ''}>
            {f.event === 'user' ? (
              <div className="rounded-xl bg-zinc-900 px-4 py-2 text-sm text-white">{f.data.message}</div>
            ) : f.event === 'result' && f.data.chart === 'line' && Array.isArray(f.data.rows) && f.data.rows.length >= 2 ? (
              <div key="line" className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
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
                      <button key={j} className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs" onClick={() => void ask(`按${o.label}的商品排行`)}>
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
        {busy && <div className="text-xs text-zinc-400">正在解析问题并查询…</div>}
      </div>
      <div className="border-t border-zinc-200 bg-white px-6 py-4">
        <div className="flex gap-3">
          <input
            id="analytics-input"
            className="flex-1 rounded-xl border border-zinc-300 px-4 py-2.5 text-sm outline-none focus:border-zinc-900"
            placeholder="问点什么:上个月 GMV 趋势 / 卖得最差的商品 / 为什么退货变多了"
            onKeyDown={(e) => { if (e.key === 'Enter') { const v = (e.target as HTMLInputElement).value; (e.target as HTMLInputElement).value = ''; void ask(v); } }}
          />
          <Button onClick={() => { const el = document.getElementById('analytics-input') as HTMLInputElement; const v = el.value; el.value = ''; void ask(v); }} disabled={busy}>
            发送
          </Button>
          <Button variant="outline" onClick={() => void genReport()}>生成报告</Button>
        </div>
        {reportMsg && <div className="mt-2 text-[11px] text-zinc-400">{reportMsg}(角色:{role || '—'})</div>}
      </div>
    </div>
  );
}
