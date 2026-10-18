import { errMsgOf } from '@/lib/api';
import { type ReactNode, useState } from 'react';
import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from 'ui';

/** 新增/编辑弹窗骨架单点(2026-10-15 候选④):chrome + footer + busy/err 状态机。
 *  此前 13 份手抄骨架 ≈280 行、busy 防重复提交仅 1/13(promo-dialog)—— 其余
 *  12 个弹窗请求在途时可再点(双 PATCH 面)。
 *
 *  契约:onSubmit 自行完成提交并经调用方 onMsg 报成功文案,返回
 *  - `null` → 成功,壳自动 onClose;
 *  - `string` → 失败,文案留窗内(窗不关);
 *  - throw → 传输层失败,文案留窗内。
 *  壳不碰 api 不碰表单内容(children 自由)—— 万能表单配置化明确不做
 *  (promo-dialog 395 行收不进,config-object swamp;deletion test 不通过)。 */
export function FormDialogShell({
  title,
  subtitle,
  maxWidth = 'max-w-sm',
  submitLabel,
  submitDisabled = false,
  onSubmit,
  onClose,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  maxWidth?: string;
  submitLabel: string;
  submitDisabled?: boolean;
  onSubmit: () => Promise<string | null>;
  onClose: () => void;
  children: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  async function submit() {
    if (busy) return;
    setBusy(true);
    setErr('');
    try {
      const fail = await onSubmit();
      if (fail == null) {
        onClose();
        return;
      }
      setErr(fail);
    } catch (e) {
      setErr(errMsgOf(e, String(e)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      {/* p-6 是壳的职责:ui DialogContent 本体不带 padding(消费方自给,apps/admin
          ConfirmDialog 先例);32ea113 收口时抄丢曾致 13 弹窗内容贴边(标题顶圆角、
          X 坠到标题下一行),e2e ui-contract 与本目录单测双钉。 */}
      <DialogContent className={`${maxWidth} rounded-xl border-zinc-200 p-6 text-zinc-900 shadow-xl`}>
        <DialogHeader className="pb-3 border-b border-zinc-100">
          <DialogTitle className="text-base font-bold text-zinc-900">{title}</DialogTitle>
          {subtitle ? <p className="mt-1 text-xs text-zinc-500">{subtitle}</p> : null}
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto py-4 text-xs">{children}</div>
        {err && <div className="pb-1 text-[11px] text-red-600">{err}</div>}
        <DialogFooter className="gap-2 border-t border-zinc-100 pt-3 sm:gap-0">
          <Button type="button" variant="outline" size="sm" onClick={onClose} className="cursor-pointer text-xs">
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={busy || submitDisabled}
            onClick={() => void submit()}
            className="cursor-pointer text-xs font-bold"
          >
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
