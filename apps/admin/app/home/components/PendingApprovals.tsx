import type React from 'react';
import { useState } from 'react';
import {
  Activity,
  ApprovalRiskBadge,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CheckCircle2,
  Input,
  Loader2,
  MessageSquare,
  ShieldAlert,
  XCircle,
} from 'ui';
import type { Approval } from '../hooks/types';
import { HumanChatModal } from './HumanChatModal';

interface PendingApprovalsProps {
  pendingApprovals: Approval[];
  rejectionReasons: Record<string, string>;
  setRejectionReasons: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  submittingActionId: string | null;
  handleApprovalAction: (approvalId: string, action: 'approve' | 'reject') => Promise<void>;
  handleHumanReplyAction?: (approvalId: string, replyMessage: string, isFinish?: boolean) => Promise<unknown>;
}

export function PendingApprovals({
  pendingApprovals,
  rejectionReasons,
  setRejectionReasons,
  submittingActionId,
  handleApprovalAction,
  handleHumanReplyAction,
}: PendingApprovalsProps) {
  const [selectedChatApproval, setSelectedChatApproval] = useState<Approval | null>(null);
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <ShieldAlert className="h-5 w-5 text-amber-500 animate-pulse" />
          <h2 className="text-sm font-bold tracking-wider uppercase text-slate-300">
            🛡️ 安全红线拦截：待人工核准工单 ({pendingApprovals.length})
          </h2>
        </div>
        <span className="text-[10px] font-mono text-slate-500 uppercase">Real-time approval dispatch queue</span>
      </div>

      {pendingApprovals.length === 0 ? (
        <div className="bg-slate-900/30 border border-slate-850 rounded-2xl py-14 text-center space-y-3">
          <CheckCircle2 className="h-10 w-10 text-emerald-500/80 mx-auto" />
          <p className="text-xs text-slate-400">当前大盘一片绿灯！所有待审批工单已全部核签完成。</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {pendingApprovals.map((approval) => {
            const args = approval.actionPayload?.args || {};
            const isSubmitting = submittingActionId === approval.id;

            return (
              <Card
                key={approval.id}
                className="bg-slate-900 border-amber-500/30 hover:border-amber-500/50 overflow-hidden shadow-xl transition-all"
              >
                {/* Header */}
                <CardHeader className="bg-amber-500/10 px-5 py-4 border-b border-amber-500/20 flex flex-row justify-between items-center space-y-0">
                  <div className="flex items-center space-x-2">
                    <Activity className="h-4 w-4 text-amber-400 animate-spin-slow" />
                    <span className="text-xs font-bold text-amber-300 uppercase tracking-wider font-mono">
                      {approval.actionType}
                    </span>
                  </div>
                  <ApprovalRiskBadge actionType={approval.actionType} status={approval.status} />
                </CardHeader>

                {/* Content */}
                <CardContent className="p-5 space-y-4">
                  {/* Metadatas */}
                  <div className="space-y-1 text-xs">
                    <div className="flex justify-between">
                      <span className="text-slate-500">商户租户:</span>
                      <span className="font-mono text-indigo-400 font-bold uppercase">
                        {approval.businessId || 'ecommerce'}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">工单 ID:</span>
                      <span className="font-mono text-slate-300">{approval.id.substring(0, 8)}...</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Thread ID:</span>
                      <span className="font-mono text-slate-300 truncate max-w-[150px]">{approval.threadId}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">截止日期:</span>
                      <span className="font-mono text-amber-400/80">
                        {approval.deadline
                          ? new Date(approval.deadline).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                            })
                          : '-'}
                      </span>
                    </div>
                  </div>

                  {/* Payload Visualization */}
                  <div className="bg-slate-950 border border-slate-850 rounded-xl p-3.5 space-y-2.5">
                    <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest block font-mono">
                      ACTION PAYLOAD DETAILS
                    </span>
                    <div className="text-xs font-mono text-slate-300 space-y-1.5 overflow-x-auto">
                      {Object.entries(args).map(([k, v]) => (
                        <div key={k} className="flex gap-2">
                          <span className="text-slate-500">{k}:</span>
                          <span className="text-indigo-300">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Actions Form */}
                  <div className="space-y-2">
                    <Button
                      type="button"
                      onClick={() => setSelectedChatApproval(approval)}
                      className="w-full h-8 text-[11px] font-bold bg-indigo-600/30 hover:bg-indigo-600/50 border border-indigo-500/40 text-indigo-200 rounded-xl flex items-center justify-center gap-1.5 transition"
                    >
                      <MessageSquare className="h-3.5 w-3.5 text-indigo-400" />
                      <span>💬 客服接管 / IM 对话</span>
                    </Button>

                    <Input
                      type="text"
                      value={rejectionReasons[approval.id] || ''}
                      onChange={(e) =>
                        setRejectionReasons((prev) => ({
                          ...prev,
                          [approval.id]: e.target.value,
                        }))
                      }
                      placeholder="驳回请在此输入拒绝理由..."
                      className="bg-slate-950 border-slate-850 text-slate-100 placeholder-slate-600 focus-visible:ring-indigo-500 text-xs"
                    />

                    <div className="flex gap-2 pt-1">
                      <Button
                        type="button"
                        onClick={() => handleApprovalAction(approval.id, 'approve')}
                        disabled={isSubmitting}
                        className="flex-1 h-8 text-[11px] font-bold bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl flex items-center justify-center gap-1.5"
                      >
                        {isSubmitting ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <>
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            <span>核准通过</span>
                          </>
                        )}
                      </Button>
                      <Button
                        type="button"
                        onClick={() => handleApprovalAction(approval.id, 'reject')}
                        disabled={isSubmitting}
                        className="flex-1 h-8 text-[11px] font-bold bg-rose-600 hover:bg-rose-500 text-white rounded-xl flex items-center justify-center gap-1.5"
                      >
                        {isSubmitting ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <>
                            <XCircle className="h-3.5 w-3.5" />
                            <span>驳回申请</span>
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Human Support Chat & Escalation Modal */}
      <HumanChatModal
        approval={selectedChatApproval}
        isOpen={Boolean(selectedChatApproval)}
        onClose={() => setSelectedChatApproval(null)}
        onSendReply={async (approvalId, replyMsg, isFinish) => {
          if (handleHumanReplyAction) {
            await handleHumanReplyAction(approvalId, replyMsg, isFinish);
          }
        }}
      />
    </section>
  );
}
