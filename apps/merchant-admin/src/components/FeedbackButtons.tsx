import { useState } from 'react';
import { Button, Input } from 'ui';

export type FeedbackVerdict = 'up' | 'down';

/** 答案反馈按钮组(反馈闭环 v3.1):受控组件,评分态(rated)由宿主持有 ——
 *  FloatingAgent 随 localStorage 历史持久化,/analytics 页随会话内存。
 *  👍 直提;👎 先展开可选备注(再点 👎 或「提交」即发送)。提交后闩锁禁用。
 *  unsupported 帧仅开放 👎(allowUp=false,「正确拒绝」点赞是过度设计);
 *  traceId 缺失(error/clarify/旧历史帧)时宿主不渲染本组件。 */
export function FeedbackButtons({
  allowUp = true,
  rated,
  busy,
  onSubmit,
}: {
  allowUp?: boolean;
  rated?: FeedbackVerdict;
  busy?: boolean;
  onSubmit: (verdict: FeedbackVerdict, note?: string) => void;
}) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState('');
  const done = rated != null;
  // 反馈组是嵌在结果卡尾部的微缩件,统一 outline/sm + 原字号密度
  const cls = 'h-auto rounded-lg px-2 py-0.5 text-[11px] font-normal';

  return (
    <div className="mt-1.5">
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-zinc-400">这个结果{allowUp ? '有帮助吗' : '答错了吗'}?</span>
        {allowUp && (
          <Button
            type="button"
            variant="outline"
            disabled={done || busy}
            title="有帮助"
            className={`${cls} ${
              rated === 'up'
                ? 'border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-50 hover:text-emerald-700'
                : 'border-zinc-300 text-zinc-500 hover:border-zinc-900 hover:text-zinc-900'
            }`}
            onClick={() => onSubmit('up')}
          >
            👍{rated === 'up' ? ' 已反馈' : ''}
          </Button>
        )}
        <Button
          type="button"
          variant="outline"
          disabled={done || busy}
          title="没帮助"
          className={`${cls} ${
            rated === 'down'
              ? 'border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-50 hover:text-amber-700'
              : 'border-zinc-300 text-zinc-500 hover:border-zinc-900 hover:text-zinc-900'
          }`}
          onClick={() => (noteOpen ? onSubmit('down', note.trim() || undefined) : setNoteOpen(true))}
        >
          👎{rated === 'down' ? ' 已反馈' : ''}
        </Button>
      </div>
      {noteOpen && !done && (
        <div className="mt-1 flex items-center gap-1.5">
          <Input
            className="h-auto flex-1 rounded-lg border-zinc-300 px-2 py-1 text-[11px] shadow-none focus-visible:border-zinc-900 focus-visible:ring-0"
            placeholder="哪里不对?可留空(选填)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSubmit('down', note.trim() || undefined)}
          />
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            className={`${cls} border-zinc-900 bg-zinc-900 text-white hover:bg-zinc-900 hover:text-white`}
            onClick={() => onSubmit('down', note.trim() || undefined)}
          >
            提交
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            className={`${cls} border-zinc-300 text-zinc-500 hover:text-zinc-500`}
            onClick={() => {
              setNoteOpen(false);
              setNote('');
            }}
          >
            取消
          </Button>
        </div>
      )}
    </div>
  );
}
