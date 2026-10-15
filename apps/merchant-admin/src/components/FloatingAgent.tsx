import { FeedbackButtons } from '@/components/FeedbackButtons';
import { ResultCard } from '@/components/ResultCard';
import { type AskFrameData, type SessionFrame } from '@/lib/analytics-frames';
import { api } from '@/lib/api';
import {
  type AskSession,
  clarifyAskQuestion,
  createAskSession,
  currentAskSessionId,
  isFeedbackTail,
  useAskSession,
} from '@/lib/ask-session';
import { type SelectionMap, clearSelection, getSelection, getSelectionLabels, subscribe } from '@/lib/page-context';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { Button, Input } from 'ui';

// 全局悬浮 agent(19 号修订):任意路由可唤起;上下文 = 当前路由 + 列表页勾选
// (page-context 内存上行)。2026-10-15「Ask 会话」四表面收敛:帧机/断线恢复/
// 反馈闩锁/history 防抖落盘/会话身份全部下沉 lib/ask-session 单点,本组件只剩
// 面板 chrome、动作行(导出 CSV/钉看板/存报告)与 localStorage 键。

function exportResultCsv(data: AskFrameData) {
  const rows = data.rows || [];
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const esc = (v: unknown) => `"${String(v ?? '').replaceAll('"', '""')}"`;
  const lines = [cols.map(esc).join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))];
  // BOM 头:Excel 打开中文不乱码
  const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' });
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
  const [q, setQ] = useState('');
  // 勾选实时联动(T5):内存广播库订阅,勾/清即刻反映到面板横幅
  const [selMap, setSelMap] = useState<SelectionMap>({});
  useEffect(() => subscribe((s) => setSelMap({ ...s })), []);

  const sessionRef = useRef<AskSession | null>(null);
  if (!sessionRef.current) {
    sessionRef.current = createAskSession({
      getSessionId: currentAskSessionId,
      getPageContext: () => ({ route, selection: getSelection(), selectionLabels: getSelectionLabels() }),
      history: {
        load: () => {
          try {
            const saved = JSON.parse(localStorage.getItem('merchant-admin.agent.history') || '[]');
            return Array.isArray(saved) && saved.length ? (saved as SessionFrame[]) : null;
          } catch {
            return null; /* 坏档忽略 */
          }
        },
        save: (frames) => {
          try {
            localStorage.setItem('merchant-admin.agent.history', JSON.stringify(frames));
          } catch {}
        },
      },
    });
  }
  const session = sessionRef.current;
  const { frames, busy, rateBusyId } = useAskSession(session);
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

  /** 面板触发提问:问句取输入框(或就地唤起带参),实际发出交会话(busy 闸在 core)。 */
  function submit(questionOverride?: string) {
    const question = (questionOverride ?? q).trim();
    if (!question || busy) return;
    setQ('');
    void session.ask(question);
  }
  askRef.current = (qOverride?: string) => submit(qOverride);

  function newConversation() {
    // 会话清帧 + 「非空→空」立即落盘空数组(core reset);轮转会话身份 ——
    // 全屏问答页同键随动(一个员工一个当前 Ask 会话身份)
    session.reset();
    localStorage.setItem('merchant-admin.session', `s-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);
  }

  function pinToBoard(f: SessionFrame) {
    const pins = JSON.parse(localStorage.getItem('merchant-admin.board') || '[]');
    pins.push({
      id: `pin-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      question: f.question ?? '',
      route,
      pinnedAt: new Date().toISOString(),
    });
    localStorage.setItem('merchant-admin.board', JSON.stringify(pins.slice(-20)));
  }

  async function saveToReport(f: SessionFrame) {
    try {
      await api.reports.saveFromResult({
        question: f.question ?? '',
        metric: String(f.data.metric || 'result'),
        unit: String(f.data.unit || ''),
        caliber: String(f.data.caliber || ''),
        rows: f.data.rows || [],
        chart: typeof f.data.chart === 'string' ? f.data.chart : undefined,
      });
      session.markSaved(f.id);
    } catch (err) {
      session.pushError(`存报告失败:${String(err)}`);
    }
  }

  if (!open) {
    return (
      <Button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-40 flex size-14 select-none rounded-full bg-zinc-900 text-xl font-normal text-white shadow-xl hover:bg-zinc-900"
        aria-label="打开数据分析助手"
      >
        🤖
      </Button>
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
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-auto px-1 py-0.5 text-xs font-normal text-zinc-400 hover:text-zinc-900"
            onClick={() => navigate('/board')}
          >
            📌 看板
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-auto px-1 py-0.5 text-xs font-normal text-zinc-400 hover:text-zinc-900"
            onClick={newConversation}
          >
            ✚ 新对话
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-auto px-1 py-0.5 text-xs font-normal text-zinc-400 hover:text-zinc-900"
            onClick={() => setOpen(false)}
          >
            收起
          </Button>
        </div>
      </div>
      <div className="border-b border-zinc-50 px-4 py-2 flex items-center gap-2">
        <span className="rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
          上下文:{route}
        </span>
        {selMap.order?.length || selMap.spu?.length || selMap.customer?.length ? (
          <Button
            type="button"
            variant="outline"
            onClick={() => clearSelection()}
            title="勾选会作为查询上下文,点击清除"
            className="h-auto rounded-md border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-normal text-amber-700 shadow-none hover:bg-amber-50 hover:text-amber-700"
          >
            已勾选{' '}
            {(['order', 'spu', 'customer'] as const)
              .filter((k) => (selMap[k]?.length || 0) > 0)
              .map((k) => `${SEL_KIND_LABEL[k]} ${selMap[k]!.length}`)
              .join(' · ')}{' '}
            ✕
          </Button>
        ) : null}
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {frames.length === 0 && (
          <div className="text-[11px] text-zinc-400">试试:本月销量 Top10 / 差评最多的 SKU / 会话量多少</div>
        )}
        {frames.map((f, fi) => (
          <div key={f.id} className={f.event === 'user' ? 'flex justify-end' : ''}>
            {f.event === 'user' ? (
              <div className="rounded-xl bg-zinc-900 px-3 py-2 text-sm text-white">{f.data.message}</div>
            ) : f.event === 'pending' ? (
              <div className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-xs text-zinc-400">
                正在解析问题并查询…
              </div>
            ) : f.event === 'clarify' ? (
              <div className="rounded-xl border border-amber-200 bg-white p-3 text-sm">
                {String(f.data.question ?? '')}
                <div className="mt-2 flex flex-wrap gap-2">
                  {(f.data.options || []).map((o) => (
                    <Button
                      key={o.label}
                      type="button"
                      variant="outline"
                      className="rounded-lg border-zinc-300 px-3 py-1.5 text-xs font-normal shadow-none"
                      onClick={() => setQ(clarifyAskQuestion(f.data, o))}
                    >
                      {o.label}
                    </Button>
                  ))}
                </div>
              </div>
            ) : f.event === 'result' ? (
              <>
                <ResultCard data={f.data} />
                {f.data.summary ? (
                  <div className="mt-1 text-[11px] leading-relaxed text-zinc-500">
                    <span className="mr-1 rounded bg-zinc-100 px-1 py-0.5 text-[10px] text-zinc-500">速览</span>
                    {String(f.data.summary ?? '')}
                  </div>
                ) : null}
                {Array.isArray(f.data.rows) && f.data.rows.length > 0 && (
                  <div className="mt-1.5 flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      className="h-auto rounded-lg border-zinc-300 px-2.5 py-1 text-[11px] font-normal text-zinc-600 shadow-none hover:border-zinc-900 hover:text-zinc-900"
                      onClick={() => exportResultCsv(f.data)}
                    >
                      导出 CSV
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="h-auto rounded-lg border-zinc-300 px-2.5 py-1 text-[11px] font-normal text-zinc-600 shadow-none hover:border-zinc-900 hover:text-zinc-900"
                      title="钉到看板页定时重放刷新"
                      onClick={() => pinToBoard(f)}
                    >
                      📌 钉看板
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      disabled={f.saved}
                      className="h-auto rounded-lg border-zinc-300 px-2.5 py-1 text-[11px] font-normal text-zinc-600 shadow-none hover:border-zinc-900 hover:text-zinc-900 disabled:opacity-60"
                      onClick={() => void saveToReport(f)}
                    >
                      {f.saved ? '已存入我的报告 ✓' : '存为报告'}
                    </Button>
                  </div>
                )}
                {/* 反馈行在动作行闸外:诚实空结果(rows=[])同样可评 */}
                {isFeedbackTail(frames, fi) ? (
                  <FeedbackButtons
                    rated={f.rated}
                    busy={rateBusyId === f.id}
                    onSubmit={(verdict, note) => void session.rate(f.id, verdict, note)}
                  />
                ) : null}
              </>
            ) : (
              <div className="rounded-xl border border-zinc-200 bg-white p-3 text-sm">
                {String(f.data.message ?? f.event)}
                {f.data.caliber ? (
                  <div className="mt-1 text-[11px] text-zinc-400">口径:{String(f.data.caliber)}</div>
                ) : null}
                {/* 断线恢复(ADR-0013 同族):error 帧带句柄 —— 流还在 Redis(600s)、
                    生产者仍在后台跑,恢复只补剩余帧不重算;过期(流不存在)由服务端
                    error 帧诚实回「请重新提问」。句柄细节在 ask-session 单点。 */}
                {f.data.resume ? (
                  <div className="mt-2">
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy}
                      className="h-auto rounded-lg border-zinc-300 px-2.5 py-1 text-[11px] font-normal text-zinc-600 shadow-none hover:border-zinc-900 hover:text-zinc-900 disabled:opacity-60"
                      onClick={() => void session.resume(f.id)}
                    >
                      恢复结果
                    </Button>
                  </div>
                ) : null}
                {/* unsupported 帧仅开放 👎:「这问题本该能答」是词林缺口的最高价值信号 */}
                {f.event === 'unsupported' && isFeedbackTail(frames, fi) ? (
                  <FeedbackButtons
                    allowUp={false}
                    rated={f.rated}
                    busy={rateBusyId === f.id}
                    onSubmit={(verdict, note) => void session.rate(f.id, verdict, note)}
                  />
                ) : null}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="text-xs text-zinc-400">正在解析问题并查询…</div>}
      </div>
      <div className="flex shrink-0 gap-2 border-t border-zinc-100 p-3">
        <Input
          className="flex-1 rounded-lg border-zinc-300 px-3 text-sm shadow-none focus-visible:border-zinc-900 focus-visible:ring-0"
          placeholder="提问…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
        />
        <Button size="sm" disabled={busy} onClick={() => submit()}>
          发送
        </Button>
      </div>
    </div>
  );
}
