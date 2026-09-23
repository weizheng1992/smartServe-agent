import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Button } from 'ui';
import { ResultCard } from '@/components/ResultCard';
import { api } from '@/lib/api';
import { clearSelection, getSelection, getSelectionLabels, subscribe, type SelectionMap } from '@/lib/page-context';

// 全局悬浮 agent(19 号修订):任意路由可唤起;上下文 = 当前路由(选中数据
// 由列表页经 localStorage 约定键上行 —— PageContext 19-D3)。
// 阶段⑥:排行卡条形图化 + 结果卡底部「导出 CSV / 存为报告」(存入我的报告)。
// 帧带自增 id:渲染层会过滤 start 帧,按下标回写状态会错位 —— 一律按 id 回写
let frameSeq = 0;
type AgentFrame = { id: number; event: string; data: any; saved?: boolean };

function exportResultCsv(data: any) {
  const rows: any[] = data.rows || [];
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const esc = (v: unknown) => `"${String(v ?? '').replaceAll('"', '""')}"`;
  const lines = [cols.map(esc).join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))];
  // BOM 头:Excel 打开中文不乱码
  const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${data.metric || 'result'}-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

const SEL_KIND_LABEL: Record<string, string> = { order: '订单', spu: '商品', customer: '客户' };

export function FloatingAgent({ route }: { route: string }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [frames, setFrames] = useState<AgentFrame[]>([]);
  const [q, setQ] = useState('');
  // 勾选实时联动(T5):内存广播库订阅,勾/清即刻反映到面板横幅
  const [selMap, setSelMap] = useState<SelectionMap>({});
  useEffect(() => subscribe((s) => setSelMap({ ...s })), []);
  const askRef = useRef<(q?: string) => void>(() => {});

  // 就地唤起(如订单页「向 AI 提问」):开面板 + 自动提问,不跳页
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail || {};
      setOpen(true);
      if (detail.question) askRef.current?.(String(detail.question));
    };
    window.addEventListener('merchant-admin:open-agent', handler);
    return () => window.removeEventListener('merchant-admin:open-agent', handler);
  }, []);

  async function ask(questionOverride?: string) {
    const question = (questionOverride ?? q).trim();
    if (!question || busy) return;
    setBusy(true);
    const selection = getSelection();
    // T3 多轮:浏览器侧稳定 session_id(服务端 Redis 按此键存会话上下文)
    let sessionId = localStorage.getItem('merchant-admin.session');
    if (!sessionId) {
      sessionId = `s-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      localStorage.setItem('merchant-admin.session', sessionId);
    }
    try {
      const result = await api.ask(question, { route, selection, selectionLabels: getSelectionLabels(), sessionId });
      const stamp = ++frameSeq * 100;
      setFrames((prev) => [
        ...prev,
        { id: stamp, event: 'user', data: { message: question } },
        ...result.map((f: any, k: number) => ({
          id: stamp + k + 1,
          event: f.event,
          data: f.event === 'result' ? { ...f.data, __question: question } : f.data,
        })),
      ]);
    } catch (err) {
      setFrames((prev) => [...prev, { id: ++frameSeq, event: 'error', data: { message: String(err) } }]);
    }
    setQ('');
    setBusy(false);
  }
  askRef.current = (qOverride?: string) => void ask(qOverride);

  function pinToBoard(data: any) {
    const pins = JSON.parse(localStorage.getItem('merchant-admin.board') || '[]');
    pins.push({
      id: `pin-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      question: String(data.__question || ''),
      route,
      pinnedAt: new Date().toISOString(),
    });
    localStorage.setItem('merchant-admin.board', JSON.stringify(pins.slice(-20)));
  }

  async function saveToReport(frame: AgentFrame) {
    try {
      await api.reports.saveFromResult({
        question: frame.data.__question || '',
        metric: String(frame.data.metric || 'result'),
        unit: String(frame.data.unit || ''),
        caliber: String(frame.data.caliber || ''),
        rows: frame.data.rows || [],
        chart: frame.data.chart || undefined,
      });
      setFrames((prev) => prev.map((f) => (f.id === frame.id ? { ...f, saved: true } : f)));
    } catch (err) {
      setFrames((prev) => [...prev, { id: ++frameSeq, event: 'error', data: { message: `存报告失败:${String(err)}` } }]);
    }
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
        <div className="flex items-center gap-2">
          <button type="button" className="text-xs text-zinc-400 hover:text-zinc-900" onClick={() => navigate('/board')}>
            📌 看板
          </button>
          <button type="button" className="text-xs text-zinc-400 hover:text-zinc-900" onClick={() => setOpen(false)}>
            收起
          </button>
        </div>
      </div>
      <div className="border-b border-zinc-50 px-4 py-2 flex items-center gap-2">
        <span className="rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
          上下文:{route}
        </span>
        {(selMap.order?.length || selMap.spu?.length || selMap.customer?.length) ? (
          <button
            type="button"
            onClick={() => clearSelection()}
            title="勾选会作为查询上下文,点击清除"
            className="rounded-md border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700"
          >
            已勾选 {(['order', 'spu', 'customer'] as const)
              .filter((k) => (selMap[k]?.length || 0) > 0)
              .map((k) => `${SEL_KIND_LABEL[k]} ${selMap[k]!.length}`)
              .join(' · ')} ✕
          </button>
        ) : null}
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
              <>
                <ResultCard data={f.data} />
                {Array.isArray(f.data.rows) && f.data.rows.length > 0 && (
                  <div className="mt-1.5 flex gap-2">
                    <button
                      type="button"
                      className="rounded-lg border border-zinc-300 px-2.5 py-1 text-[11px] text-zinc-600 hover:border-zinc-900 hover:text-zinc-900"
                      onClick={() => exportResultCsv(f.data)}
                    >
                      导出 CSV
                    </button>
                    <button
                      type="button"
                      className="rounded-lg border border-zinc-300 px-2.5 py-1 text-[11px] text-zinc-600 hover:border-zinc-900 hover:text-zinc-900"
                      title="钉到看板页定时重放刷新"
                      onClick={() => pinToBoard(f.data)}
                    >
                      📌 钉看板
                    </button>
                    <button
                      type="button"
                      disabled={f.saved}
                      className="rounded-lg border border-zinc-300 px-2.5 py-1 text-[11px] text-zinc-600 hover:border-zinc-900 hover:text-zinc-900 disabled:opacity-60"
                      onClick={() => void saveToReport(f)}
                    >
                      {f.saved ? '已存入我的报告 ✓' : '存为报告'}
                    </button>
                  </div>
                )}
              </>
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
