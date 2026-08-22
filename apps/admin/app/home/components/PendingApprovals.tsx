import type React from "react";
import { useState } from "react";
import {
  ApprovalContextDrawer,
  CheckCircle2,
  HumanChatModal,
  PendingApprovalCard,
  ShieldAlert,
} from "ui";
import type { Approval } from "../hooks/types";

interface PendingApprovalsProps {
  pendingApprovals: Approval[];
  rejectionReasons: Record<string, string>;
  setRejectionReasons: React.Dispatch<
    React.SetStateAction<Record<string, string>>
  >;
  submittingActionId: string | null;
  handleApprovalAction: (
    approvalId: string,
    action: "approve" | "reject",
    reason?: string,
  ) => Promise<void>;
  handleHumanReplyAction?: (
    approvalId: string,
    replyMessage: string,
    isFinish?: boolean,
  ) => Promise<unknown>;
  onOpenChatModal?: (approval: Approval) => void;
  onInspectApproval?: (approval: Approval) => void;
}

export function PendingApprovals({
  pendingApprovals,
  rejectionReasons,
  setRejectionReasons,
  submittingActionId,
  handleApprovalAction,
  handleHumanReplyAction,
  onOpenChatModal,
  onInspectApproval,
}: PendingApprovalsProps) {
  const [selectedChatApproval, setSelectedChatApproval] =
    useState<Approval | null>(null);
  const [inspectingApproval, setInspectingApproval] = useState<Approval | null>(
    null,
  );

  const handleOpenChat = (approval: Approval) => {
    if (onOpenChatModal) {
      onOpenChatModal(approval);
    } else {
      setSelectedChatApproval(approval);
    }
  };

  const handleInspect = (approval: Approval) => {
    if (onInspectApproval) {
      onInspectApproval(approval);
    } else {
      setInspectingApproval(approval);
    }
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <ShieldAlert className="h-5 w-5 text-amber-500 animate-pulse" />
          <h2 className="text-sm font-bold tracking-wider uppercase text-slate-300">
            🛡️ 安全红线拦截：待人工核准工单 ({pendingApprovals.length})
          </h2>
        </div>
        <span className="text-[10px] font-mono text-slate-500 uppercase">
          Real-time approval dispatch queue
        </span>
      </div>

      {pendingApprovals.length === 0 ? (
        <div className="bg-slate-900/30 border border-slate-850 rounded-2xl py-14 text-center space-y-3">
          <CheckCircle2 className="h-10 w-10 text-emerald-500/80 mx-auto" />
          <p className="text-xs text-slate-400">
            当前大盘一片绿灯！所有待审批工单已全部核签完成。
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {pendingApprovals.map((approval) => (
            <PendingApprovalCard
              key={approval.id}
              approval={approval}
              rejectionReason={rejectionReasons[approval.id] || ""}
              setRejectionReason={(val) =>
                setRejectionReasons((prev) => ({
                  ...prev,
                  [approval.id]: val,
                }))
              }
              isSubmitting={submittingActionId === approval.id}
              onApprove={(id) => handleApprovalAction(id, "approve")}
              onReject={(id) =>
                handleApprovalAction(
                  id,
                  "reject",
                  rejectionReasons[approval.id],
                )
              }
              onOpenChat={handleOpenChat}
              onInspect={handleInspect}
            />
          ))}
        </div>
      )}

      {/* 🔍 Trigger Cause, User Profile, Purchase Records & Full Chat Inspector Drawer */}
      <ApprovalContextDrawer
        isOpen={Boolean(inspectingApproval)}
        onClose={() => setInspectingApproval(null)}
        approval={inspectingApproval}
        onApprove={async (id) => {
          await handleApprovalAction(id, "approve");
        }}
        onReject={async (id, reason) => {
          await handleApprovalAction(id, "reject", reason);
        }}
        onHumanReply={async (id, replyMsg, isFinish) => {
          if (handleHumanReplyAction) {
            await handleHumanReplyAction(id, replyMsg, isFinish);
          }
        }}
      />

      {/* Human Support Chat & Escalation Modal (Fallback if no parent modal handler) */}
      {!onOpenChatModal && (
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
      )}
    </section>
  );
}
