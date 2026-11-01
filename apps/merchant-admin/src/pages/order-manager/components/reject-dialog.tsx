import { FormDialogShell } from '@/components/form-dialog-shell';
import { Button, Label, Textarea } from 'ui';
import { useWorkbench } from '../workbench';

const REJECT_TEMPLATES = [
  '物流已签收，驳回退款诉求',
  '已超过售后服务有效退款窗口',
  '商品已拆封使用，不满足退货条件',
  '请提供清晰的商品破损照片后再试',
];

/** 驳回原因弹窗:直传显式原因(工单 04 修复 state 闭包吞文案问题)。
 *  收编 FormDialogShell(2026-10-31 盲区清偿):busy 防重复提交走壳;
 *  失败可见性沿用 handleApprovalAction 的 alert 报告(与旧实现行为一致,
 *  提交后关窗 —— 壳契约的「失败留窗」需 handleApprovalAction 改返回值,未动)。 */
export function RejectDialog() {
  const { rejectingApprovalId, setRejectingApprovalId, rejectReasonInput, setRejectReasonInput, handleApprovalAction } =
    useWorkbench();

  if (!rejectingApprovalId) return null;

  return (
    <FormDialogShell
      title="驳回审批工单"
      subtitle={<span className="font-mono">工单 ID: {rejectingApprovalId}</span>}
      maxWidth="max-w-md"
      submitLabel="确认驳回"
      onClose={() => {
        setRejectingApprovalId(null);
        setRejectReasonInput('');
      }}
      onSubmit={async () => {
        if (!rejectingApprovalId) return '工单缺失';
        await handleApprovalAction(rejectingApprovalId, 'reject', rejectReasonInput);
        return null;
      }}
    >
      <Label htmlFor="reject-reason" className="block text-xs font-semibold text-zinc-700">
        请输入驳回原因 (将通知顾客并载入会话工作流)
      </Label>
      <Textarea
        id="reject-reason"
        value={rejectReasonInput}
        onChange={(e) => setRejectReasonInput(e.target.value)}
        rows={3}
        placeholder="例如：物流轨迹显示已由本人签收，不符合退款条件..."
        className="w-full text-xs p-2.5 border border-zinc-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-rose-500 bg-white"
      />
      <div className="flex flex-wrap gap-1.5 pt-1">
        <span className="text-[11px] text-zinc-400">常用快捷模板:</span>
        {REJECT_TEMPLATES.map((tpl) => (
          <Button
            key={tpl}
            type="button"
            variant="ghost"
            onClick={() => setRejectReasonInput(tpl)}
            className="h-auto cursor-pointer rounded bg-zinc-100 px-2 py-0.5 text-[11px] font-normal text-zinc-700 transition hover:bg-zinc-200 hover:text-zinc-700"
          >
            {tpl}
          </Button>
        ))}
      </div>
    </FormDialogShell>
  );
}
