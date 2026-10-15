import { type AskStreamError, api } from '@/lib/api';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button } from 'ui';
import { AskInputBar } from './components/ask-input-bar';
import { type AskFrame, AskTranscript } from './components/ask-transcript';

const CAPSULES = [
  '本月销量 Top10',
  '卖得最差的商品',
  '差评最多的 SKU',
  '近 30 天退款率',
  '售后工单概况',
  '客服负载概况',
];

// 全屏工作台(16 号):多轮深聊/多卡;与悬浮共享同一后端 ask。
// 页面只持有会话状态(帧流水/busy/报告消息),卡片渲染与输入栏拆至 components/。
export default function AnalyticsPage({ role }: { role: string }) {
  const [frames, setFrames] = useState<AskFrame[]>([]);
  const [busy, setBusy] = useState(false);
  const [reportMsg, setReportMsg] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  /** 错误帧落屏:AskStreamError 附恢复句柄(流留 Redis 600s,恢复不重算;
   *  question 由调用侧带入 —— 错误对象只携 askId/lastEventId)。 */
  const appendError = useCallback((err: unknown, question: string) => {
    setFrames((p) => [
      ...p,
      {
        event: 'error',
        data: {
          message: String(err),
          ...(err instanceof Error && err.name === 'AskStreamError'
            ? {
                resume: {
                  askId: (err as AskStreamError).askId,
                  lastEventId: (err as AskStreamError).lastEventId,
                  question,
                },
              }
            : {}),
        },
      } as AskFrame,
    ]);
  }, []);

  const ask = useCallback(
    async (question: string) => {
      if (!question.trim() || busy) return;
      setBusy(true);
      setFrames((p) => [...p, { event: 'user', data: { message: question } }]);
      try {
        // 流式:每凑齐一帧即上屏(含 clarify/result/unsupported,不再整段等待)
        await api.ask(question, undefined, (f) => setFrames((p) => [...p, f]));
      } catch (err) {
        appendError(err, question);
      }
      setBusy(false);
      requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 1e9 }));
    },
    [busy, appendError],
  );

  /** 断线恢复(ADR-0013 同族,全屏面版):携句柄重进流只补帧不重算;
   *  旧错误帧按句柄匹配摘除 —— 成功不留失效按钮,再失败只留最新句柄。 */
  const resumeAsk = useCallback(
    async (resume: { askId: string; lastEventId: number; question: string }) => {
      if (busy) return;
      setBusy(true);
      try {
        await api.ask(resume.question, undefined, (f) => setFrames((p) => [...p, f]), {
          askId: resume.askId,
          lastEventId: resume.lastEventId,
        });
        setFrames((p) =>
          p.filter(
            (f) => !(f.event === 'error' && (f.data.resume as { askId?: string } | undefined)?.askId === resume.askId),
          ),
        );
      } catch (err) {
        // 摘旧句柄帧后落新错误帧(只留最新句柄,不堆「恢复结果」按钮)
        setFrames((p) =>
          p.filter(
            (f) => !(f.event === 'error' && (f.data.resume as { askId?: string } | undefined)?.askId === resume.askId),
          ),
        );
        appendError(err, resume.question);
      }
      setBusy(false);
      requestAnimationFrame(() => scrollRef.current?.scrollTo({ top: 1e9 }));
    },
    [busy, appendError],
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: 挂载即发出首问(仅一次)
  useEffect(() => {
    void ask('本月销量 Top10');
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
            onClick={() => void ask(c)}
          >
            {c}
          </Button>
        ))}
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        <AskTranscript frames={frames} onAsk={(q) => void ask(q)} onResume={(h) => void resumeAsk(h)} busy={busy} />
        {busy && <div className="text-xs text-zinc-400">正在解析问题并查询…</div>}
      </div>
      <AskInputBar
        busy={busy}
        onAsk={(q) => void ask(q)}
        onGenReport={() => void genReport()}
        reportMsg={reportMsg}
        roleName={role}
      />
    </div>
  );
}
