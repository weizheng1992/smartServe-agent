import { Button, Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, Textarea } from "ui";
import { useWorkbench } from "../workbench";

const REJECT_TEMPLATES = [
  '物流已签收，驳回退款诉求',
  '已超过售后服务有效退款窗口',
  '商品已拆封使用，不满足退货条件',
  '请提供清晰的商品破损照片后再试',
];

/** 驳回原因弹窗:直传显式原因(工单 04 修复 state 闭包吞文案问题)。 */
export function RejectDialog() {
  const {
    rejectingApprovalId, setRejectingApprovalId, rejectReasonInput, setRejectReasonInput,
    submittingActionId, setRejectionReasons, handleApprovalAction,
  } = useWorkbench();

  return (
    <Dialog open={Boolean(rejectingApprovalId)} onOpenChange={(open) => !open && setRejectingApprovalId(null)}>
      <DialogContent className="max-w-md p-6 bg-white text-slate-900 border-slate-200">
        <DialogHeader className="pb-3 border-b border-slate-100">
          <DialogTitle className="text-base font-bold text-slate-900">驳回审批工单</DialogTitle>
          <p className="text-xs text-slate-500 mt-1 font-mono">工单 ID: {rejectingApprovalId}</p>
        </DialogHeader>

        <div className="space-y-3 py-3">
          <label htmlFor="reject-reason" className="block text-xs font-semibold text-slate-700">
            请输入驳回原因 (将通知顾客并载入会话工作流)
          </label>
          <Textarea
            id="reject-reason"
            value={rejectReasonInput}
            onChange={(e) => setRejectReasonInput(e.target.value)}
            rows={3}
            placeholder="例如：物流轨迹显示已由本人签收，不符合退款条件..."
            className="w-full text-xs p-2.5 border border-slate-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-rose-500 bg-white"
          />
          <div className="flex flex-wrap gap-1.5 pt-1">
            <span className="text-[11px] text-slate-400">常用快捷模板:</span>
            {REJECT_TEMPLATES.map((tpl) => (
              <button
                key={tpl}
                type="button"
                onClick={() => setRejectReasonInput(tpl)}
                className="text-[11px] bg-slate-100 hover:bg-slate-200 text-slate-700 px-2 py-0.5 rounded cursor-pointer transition"
              >
                {tpl}
              </button>
            ))}
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0 pt-3 border-t border-slate-100">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setRejectingApprovalId(null);
              setRejectReasonInput('');
            }}
            className="text-xs cursor-pointer"
          >
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={submittingActionId === rejectingApprovalId}
            onClick={async () => {
              if (!rejectingApprovalId) return;
              if (rejectReasonInput) {
                setRejectionReasons((prev: Record<string, string>) => ({
                  ...prev,
                  [rejectingApprovalId]: rejectReasonInput,
                }));
              }
              await handleApprovalAction(rejectingApprovalId, 'reject', rejectReasonInput);
              setRejectingApprovalId(null);
              setRejectReasonInput('');
            }}
            className="bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold cursor-pointer"
          >
            确认驳回
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
