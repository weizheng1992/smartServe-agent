import { api } from '@/lib/api';
import { type AskSession, createAskSession, currentAskSessionId, useAskSession } from '@/lib/ask-session';
import { getSelection, getSelectionLabels } from '@/lib/page-context';
import { useEffect, useRef, useState } from 'react';
import { Button } from 'ui';
import { AskInputBar } from './components/ask-input-bar';
import { AskTranscript } from './components/ask-transcript';

const CAPSULES = [
  '本月销量 Top10',
  '卖得最差的商品',
  '差评最多的 SKU',
  '近 30 天退款率',
  '售后工单概况',
  '客服负载概况',
];

// 全屏工作台(16 号):多轮深聊/多卡;与悬浮共享同一后端 ask。
// 2026-10-15 起:会话状态归 lib/ask-session 单点 —— 页面只剩编排(胶囊/
// 输入栏/报告生成),帧机/断线恢复/会话身份/勾选上行全部由 Ask 会话承担。
// sessionId 与悬浮面板同键(merchant-admin.session),面板「新对话」轮转后
// 本页下一问随入新会话(一个员工一个当前 Ask 会话身份)。
export default function AnalyticsPage({ role }: { role: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [reportMsg, setReportMsg] = useState('');
  const sessionRef = useRef<AskSession | null>(null);
  if (!sessionRef.current) {
    sessionRef.current = createAskSession({
      getSessionId: currentAskSessionId,
      getPageContext: () => ({
        route: '/analytics',
        selection: getSelection(),
        selectionLabels: getSelectionLabels(),
      }),
    });
  }
  const session = sessionRef.current;
  const { frames, busy, rateBusyId } = useAskSession(session);

  // 帧流水增长即贴底(流式逐帧入列,不再等整轮)
  // biome-ignore lint/correctness/useExhaustiveDependencies: frames.length 是派生触发器(帧增长即贴底),体内刻意不读取
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 1e9 });
  }, [frames.length]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: 挂载即发出首问(仅一次)
  useEffect(() => {
    void session.ask('本月销量 Top10');
  }, []);

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
          <Button
            key={c}
            type="button"
            variant="outline"
            className="rounded-full border-zinc-200 bg-white px-3 py-1.5 text-xs font-normal shadow-none hover:border-zinc-900"
            onClick={() => void session.ask(c)}
          >
            {c}
          </Button>
        ))}
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        <AskTranscript
          frames={frames}
          onAsk={(q) => void session.ask(q)}
          onResume={(f) => void session.resume(f.id)}
          onRate={(f, v, note) => void session.rate(f.id, v, note)}
          rateBusyId={rateBusyId}
          busy={busy}
        />
        {busy && <div className="text-xs text-zinc-400">正在解析问题并查询…</div>}
      </div>
      <AskInputBar
        busy={busy}
        onAsk={(q) => void session.ask(q)}
        onGenReport={() => void genReport()}
        reportMsg={reportMsg}
        roleName={role}
      />
    </div>
  );
}
