import type React from 'react';
import type { PendingApprovalRecord } from 'types';
import { ApprovalRiskBadge, Button, Card, CardContent, CheckCircle2, Input, Loader2, Shield, XCircle } from 'ui';

interface ApprovalDetailViewProps {
  selectedApproval: PendingApprovalRecord | undefined;
  rejectionInput: string;
  setRejectionReason: (val: string) => void;
  isSubmitting: boolean;
  handleApprovalAction: (approvalId: string, action: 'approve' | 'reject') => Promise<void>;
  setActiveTab: (tab: 'CHAT_DESK' | 'AUDIT_DESK') => void;
}

export function ApprovalDetailView({
  selectedApproval,
  rejectionInput,
  setRejectionReason,
  isSubmitting,
  handleApprovalAction,
  setActiveTab,
}: ApprovalDetailViewProps) {
  if (!selectedApproval) {
    return (
      <div className="flex-1 bg-slate-900/20 border border-slate-900 rounded-2xl p-6 overflow-y-auto">
        <div className="h-full flex flex-col items-center justify-center text-center gap-3">
          <Shield className="h-10 w-10 text-slate-850" />
          <h3 className="text-sm font-semibold text-slate-400">请在左侧选择一个安全核签工单</h3>
          <p className="text-xs text-slate-600 max-w-[280px]">
            选择工单后，此处将全量展示拦截现场的业务上下文、参数序列、及管理员审批决策动作。
          </p>
        </div>
      </div>
    );
  }

  const deadlineObj = selectedApproval.deadline
    ? new Date(selectedApproval.deadline as string | number | Date)
    : new Date();
  const isExpired = new Date() > deadlineObj;
  const formattedPayload = JSON.stringify(
    selectedApproval.actionPayload?.args || selectedApproval.actionPayload || {},
    null,
    2,
  );

  return (
    <div className="flex-1 bg-slate-900/20 border border-slate-900 rounded-2xl p-6 overflow-y-auto">
      <div className="space-y-6">
        {/* Top detail head */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-slate-100 font-mono">工单: {selectedApproval.id}</span>
              <ApprovalRiskBadge actionType={selectedApproval.actionType} status={selectedApproval.status} />
            </div>
            <p className="text-xs text-slate-500">
              拦截触发时间:{' '}
              {selectedApproval.createdAt
                ? new Date(selectedApproval.createdAt as string | number | Date).toLocaleString()
                : '未知'}
            </p>
          </div>
        </div>

        {/* Detail metadata cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card className="bg-slate-900 border-slate-850">
            <CardContent className="p-4 space-y-1.5">
              <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                会话通道 (Thread Session)
              </span>
              <span className="text-xs font-semibold text-slate-300 block font-mono leading-relaxed truncate">
                {selectedApproval.threadId}
              </span>
            </CardContent>
          </Card>
          <Card className="bg-slate-900 border-slate-850">
            <CardContent className="p-4 space-y-1.5">
              <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
                截止自动释放日期 (Deadline)
              </span>
              <span
                className={`text-xs font-semibold block font-mono leading-relaxed ${
                  isExpired && selectedApproval.status === 'waiting' ? 'text-rose-400' : 'text-slate-300'
                }`}
              >
                {deadlineObj.toLocaleString()} {isExpired && selectedApproval.status === 'waiting' && ' [已超时]'}
              </span>
            </CardContent>
          </Card>
        </div>

        {/* JSON Payload arguments */}
        <div className="space-y-2">
          <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block font-semibold">
            拦截动作及物理参数 (Action Payload Arguments)
          </span>
          <div className="bg-slate-950 p-4 rounded-xl border border-slate-850 font-mono text-xs leading-relaxed text-indigo-300 whitespace-pre-wrap max-h-60 overflow-y-auto shadow-inner">
            {formattedPayload}
          </div>
        </div>

        {/* Action desk if status is waiting */}
        {selectedApproval.status === 'waiting' ? (
          <div className="space-y-4 pt-4 border-t border-slate-800">
            <div className="space-y-2">
              <span className="text-[11px] text-slate-400 font-semibold uppercase font-sans tracking-wide block">
                审核操作理由 (可留空，驳回时用户可见)
              </span>
              <Input
                type="text"
                value={rejectionInput}
                onChange={(e) => setRejectionReason(e.target.value)}
                placeholder="核准放行可留空。若驳回建议在此处输入具体的驳回原因..."
                className="w-full bg-slate-950 text-xs py-2 border-slate-850 focus-visible:ring-indigo-500 text-slate-100 rounded-xl placeholder-slate-600"
              />
            </div>

            <div className="flex gap-4">
              <Button
                onClick={async () => {
                  const actionId = selectedApproval.id;
                  await handleApprovalAction(actionId, 'approve');
                  setActiveTab('CHAT_DESK');
                }}
                disabled={isSubmitting}
                className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl h-11 text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-lg shadow-emerald-600/10"
              >
                {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4.5 w-4.5" />}
                <span>核准通过此申请 (Approve)</span>
              </Button>
              <Button
                onClick={async () => {
                  const actionId = selectedApproval.id;
                  await handleApprovalAction(actionId, 'reject');
                  setActiveTab('CHAT_DESK');
                }}
                disabled={isSubmitting}
                variant="destructive"
                className="flex-1 bg-rose-600 hover:bg-rose-500 text-white rounded-xl h-11 text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-lg shadow-rose-600/10"
              >
                {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4.5 w-4.5" />}
                <span>驳回此高危动作 (Reject)</span>
              </Button>
            </div>
          </div>
        ) : (
          <div className="p-4 bg-slate-900 border border-slate-850 rounded-xl space-y-1">
            <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">工单审计回执</span>
            <p className="text-xs text-slate-300 font-medium leading-relaxed font-sans">
              本工单已被管理员处理完成，处理决议：
              <strong
                className={`font-bold ${selectedApproval.status === 'approved' ? 'text-emerald-400' : 'text-rose-400'}`}
              >
                {selectedApproval.status === 'approved'
                  ? '已核准放行'
                  : selectedApproval.status === 'rejected'
                    ? '已驳回动作'
                    : '已被系统自动超时拦截'}
              </strong>
              。
            </p>
            {Boolean(selectedApproval.actionPayload?.rejectionReason) && (
              <p className="text-xs text-slate-500 mt-2 font-mono">
                理由/说明: &quot;
                {String(selectedApproval.actionPayload?.rejectionReason)}&quot;
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
