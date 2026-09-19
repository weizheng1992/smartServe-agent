import { useState } from 'react';
import { Button } from 'ui';
import { LineChart } from '@/components/LineChart';
import { api } from '@/lib/api';

// 全局悬浮 agent(19 号修订):任意路由可唤起;上下文 = 当前路由(选中数据
// 由列表页经 localStorage 约定键上行 —— PageContext 19-D3)。
export function FloatingAgent({ route }: { route: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [frames, setFrames] = useState<Array<{ event: string; data: any }>>([]);
  const [q, setQ] = useState('');

  async function ask() {
    if (!q.trim() || busy) return;
    setBusy(true);
    const selection = JSON.parse(localStorage.getItem('merchant-admin.selection') || '[]');
    try {
      const result = await api.ask(q.trim(), { route, selection });
      setFrames((prev) => [...prev, { event: 'user', data: { message: q.trim() } }, ...result]);
    } catch (err) {
      setFrames((prev) => [...prev, { event: 'error', data: { message: String(err) } }]);
    }
    setQ('');
    setBusy(false);
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 select-none items-center justify-center rounded-full bg-zinc-900 text-xl text-white shadow-xl"
        aria-label="打开数据分析助手"
      >
        🤖
      </button>
    );
  }

  return (
    <div className="fixed bottom-24 right-6 z-40 flex h-[520px] w-[380px] flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl">
      <div className="flex shrink-0 items-center justify-between border-b border-zinc-100 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
          数据分析助手
        </div>
        <button type="button" className="text-xs text-zinc-400 hover:text-zinc-900" onClick={() => setOpen(false)}>
          收起
        </button>
      </div>
      <div className="border-b border-zinc-50 px-4 py-2">
        <span className="rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
          上下文:{route}
        </span>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {frames.length === 0 && (
          <div className="text-[11px] text-zinc-400">试试:本月销量 Top10 / 差评最多的 SKU / 会话量多少</div>
        )}
        {frames.filter((f) => f.event !== 'start').map((f, i) => (
          <div key={i} className={f.event === 'user' ? 'flex justify-end' : ''}>
            {f.event === 'user' ? (
              <div className="rounded-xl bg-zinc-900 px-3 py-2 text-sm text-white">{f.data.message}</div>
            ) : f.event === 'clarify' ? (
              <div className="rounded-xl border border-amber-200 bg-white p-3 text-sm">
                {f.data.question}
                <div className="mt-2 flex flex-wrap gap-2">
                  {(f.data.options || []).map((o: any, j: number) => (
                    <button
                      type="button"
                      key={j}
                      className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs"
                      onClick={() => { setQ(`按${o.label}`); }}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : f.event === 'result' ? (
              <ResultCard data={f.data} />
            ) : (
              <div className="rounded-xl border border-zinc-200 bg-white p-3 text-sm">
                {f.data.message || f.event}
                {f.data.caliber ? <div className="mt-1 text-[11px] text-zinc-400">口径:{f.data.caliber}</div> : null}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="text-xs text-zinc-400">正在解析问题并查询…</div>}
      </div>
      <div className="flex shrink-0 gap-2 border-t border-zinc-100 p-3">
        <input
          className="flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm outline-none focus:border-zinc-900"
          placeholder="提问…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && void ask()}
        />
        <Button size="sm" disabled={busy} onClick={() => void ask()}>
          发送
        </Button>
      </div>
    </div>
  );
}

function ResultCard({ data }: { data: any }) {
  if (data.chart === 'line' && Array.isArray(data.rows) && data.rows.length >= 2) {
    const points = data.rows.map((r: any) => ({ label: String(Object.values(r)[0]), value: Number(Object.values(r)[1]) }));
    return (
      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 px-3 py-2 text-xs font-medium text-zinc-500">{data.metric} · {data.unit}</div>
        <LineChart points={points} unit={data.unit} />
        {data.caliber ? <div className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">口径:{data.caliber}</div> : null}
      </div>
    );
  }
  const card = (data.cards || [])[0];
  if (!card) return <div className="text-sm">{data.message || '空结果'}</div>;
  if (card.type !== 'table') return <div className="text-sm">{card.text}</div>;
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <div className="border-b border-zinc-100 px-3 py-2 text-xs font-medium text-zinc-500">{card.title}</div>
      <table className="w-full text-[12px]">
        <thead>
          <tr className="border-b border-zinc-100 text-left text-zinc-400">
            {card.columns.map((c: any) => (
              <th key={c.key} className="px-3 py-1.5 font-medium">{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {card.rows.map((r: any, i: number) => (
            <tr key={i} className="border-b border-zinc-50">
              {card.columns.map((c: any) => (
                <td key={c.key} className="px-3 py-1.5">{String(r[c.key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t border-zinc-100 px-3 py-1.5 text-[11px] text-zinc-400">口径:{card.caliber}</div>
    </div>
  );
}
