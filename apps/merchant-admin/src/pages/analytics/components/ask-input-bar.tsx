import { useState } from 'react';
import { Button } from 'ui';

interface Props {
  busy: boolean;
  onAsk: (q: string) => void;
  onGenReport: () => void;
  reportMsg: string;
  /** 当前登录视角角色(仅展示;不用 `role` 命名以免与 ARIA role 属性混淆) */
  roleName: string;
}

/** 底部输入栏(受控输入)+ 发送 + 生成报告。 */
export function AskInputBar({ busy, onAsk, onGenReport, reportMsg, roleName }: Props) {
  const [text, setText] = useState('');

  function send() {
    const q = text.trim();
    if (!q || busy) return;
    setText('');
    onAsk(q);
  }

  return (
    <div className="border-t border-zinc-200 bg-white px-6 py-4">
      <div className="flex gap-3">
        <input
          className="flex-1 rounded-xl border border-zinc-300 px-4 py-2.5 text-sm outline-none focus:border-zinc-900"
          placeholder="问点什么:上个月 GMV 趋势 / 卖得最差的商品 / 为什么退货变多了"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') send();
          }}
        />
        <Button onClick={send} disabled={busy}>
          发送
        </Button>
        <Button variant="outline" onClick={onGenReport}>
          生成报告
        </Button>
      </div>
      {reportMsg && (
        <div className="mt-2 text-[11px] text-zinc-400">
          {reportMsg}(角色:{roleName || '—'})
        </div>
      )}
    </div>
  );
}
