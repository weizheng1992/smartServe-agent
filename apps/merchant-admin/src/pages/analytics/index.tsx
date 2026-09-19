import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import { AskTranscript, type AskFrame } from './components/ask-transcript';
import { AskInputBar } from './components/ask-input-bar';

const CAPSULES = ['本月销量 Top10', '卖得最差的商品', '差评最多的 SKU', '近 30 天退款率', '售后工单概况', '客服负载概况'];

// 全屏工作台(16 号):多轮深聊/多卡;与悬浮共享同一后端 ask。
// 页面只持有会话状态(帧流水/busy/报告消息),卡片渲染与输入栏拆至 components/。
export default function AnalyticsPage({ role }: { role: string }) {
  const [frames, setFrames] = useState<AskFrame[]>([]);
  const [busy, setBusy] = useState(false);
  const [reportMsg, setReportMsg] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  const ask = useCallback(async (question: string) => {
    if (!question.trim() || busy) return;
    setBusy(true);
    setFrames((p) => [...p, { event: 'user', data: { message: question } }]);
    try {
      // 流式:每凑齐一帧即上屏(含 clarify/result/unsupported,不再整段等待)
      await api.ask(question, undefined, (f) => setFrames((p) => [...p, f]));
    } catch (err) {
      setFrames((p) => [...p, { event: 'error', data: { message: String(err) } }]);
    }
    setBusy(false);
    requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 1e9 }));
  }, [busy]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: 挂载即发出首问(仅一次)
  useEffect(() => { void ask('本月销量 Top10'); }, []);

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
      <div className="pb-1 text-[11px] text-zinc-400">建议问法:</div>
      <div className="flex flex-wrap gap-2 pb-4">
        {CAPSULES.map((c) => (
          <button key={c} type="button" className="rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-xs hover:border-zinc-900" onClick={() => void ask(c)}>
            {c}
          </button>
        ))}
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        <AskTranscript frames={frames} onAsk={(q) => void ask(q)} />
        {busy && <div className="text-xs text-zinc-400">正在解析问题并查询…</div>}
      </div>
      <AskInputBar busy={busy} onAsk={(q) => void ask(q)} onGenReport={() => void genReport()} reportMsg={reportMsg} roleName={role} />
    </div>
  );
}
