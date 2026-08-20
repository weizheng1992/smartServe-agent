import React, { useState } from "react";
import type { PendingApprovalRecord } from "types";
import {
  ApprovalRiskBadge,
  Button,
  Card,
  CardContent,
  CheckCircle2,
  Input,
  Loader2,
  MessageSquare,
  Shield,
  XCircle,
} from "ui";

interface ApprovalDetailViewProps {
  selectedApproval: PendingApprovalRecord | undefined;
  rejectionInput: string;
  setRejectionReason: (val: string) => void;
  isSubmitting: boolean;
  handleApprovalAction: (
    approvalId: string,
    action: "approve" | "reject",
  ) => Promise<void>;
  handleHumanReplyAction?: (
    approvalId: string,
    replyMessage: string,
    isFinish?: boolean,
  ) => Promise<unknown>;
  onOpenChatModal?: (approval: PendingApprovalRecord) => void;
  setActiveTab: (tab: "CHAT_DESK" | "AUDIT_DESK") => void;
}

export function ApprovalDetailView({
  selectedApproval,
  rejectionInput,
  setRejectionReason,
  isSubmitting,
  handleApprovalAction,
  handleHumanReplyAction,
  onOpenChatModal,
  setActiveTab,
}: ApprovalDetailViewProps) {
  const [humanCustomReply, setHumanCustomReply] = useState("");

  if (!selectedApproval) {
    return (
      <div className="flex-1 bg-slate-900/20 border border-slate-900 rounded-2xl p-6 overflow-y-auto">
        <div className="h-full flex flex-col items-center justify-center text-center gap-3">
          <Shield className="h-10 w-10 text-slate-850" />
          <h3 className="text-sm font-semibold text-slate-400">
            请在左侧选择一个安全核签工单
          </h3>
          <p className="text-xs text-slate-600 max-w-[280px]">
            选择工单后，此处将全量展示拦截现场的业务上下文、参数序列、及管理员审批决策动作。
          </p>
        </div>
      </div>
    );
  }

  const isHumanEscalation =
    selectedApproval.actionType === "human_escalation" ||
    selectedApproval.actionType?.includes("human") ||
    selectedApproval.actionType?.includes("escalat");

  const deadlineObj = selectedApproval.deadline
    ? new Date(selectedApproval.deadline as string | number | Date)
    : new Date();
  const isExpired = new Date() > deadlineObj;
  const formattedPayload = JSON.stringify(
    selectedApproval.actionPayload?.args ||
      selectedApproval.actionPayload ||
      {},
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
              <span className="text-sm font-bold text-slate-100 font-mono">
                工单: {selectedApproval.id}
              </span>
              <ApprovalRiskBadge
                actionType={selectedApproval.actionType}
                status={selectedApproval.status}
              />
            </div>
            <p className="text-xs text-slate-500">
              拦截触发时间:{" "}
              {selectedApproval.createdAt
                ? new Date(
                    selectedApproval.createdAt as string | number | Date,
                  ).toLocaleString()
                : "未知"}
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
                  isExpired && selectedApproval.status === "waiting"
                    ? "text-rose-400"
                    : "text-slate-300"
                }`}
              >
                {deadlineObj.toLocaleString()}{" "}
                {isExpired &&
                  selectedApproval.status === "waiting" &&
                  " [已超时]"}
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
        {selectedApproval.status === "waiting" ? (
          isHumanEscalation ? (
            /* 🎧 人工客服专属接管与回复工作台 */
            <div className="space-y-4 pt-4 border-t border-indigo-500/20 bg-indigo-950/10 p-4 rounded-2xl border border-indigo-500/30">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <MessageSquare className="h-4.5 w-4.5 text-indigo-400 animate-pulse" />
                  <span className="text-xs font-bold text-indigo-300 uppercase tracking-wider">
                    🎧 人工客服实时接管与沟通操作台
                  </span>
                </div>
                {onOpenChatModal && (
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => onOpenChatModal(selectedApproval)}
                    className="bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-[11px] h-7 px-2.5 font-bold flex items-center gap-1 shadow-md shadow-indigo-600/20"
                  >
                    <MessageSquare className="h-3 w-3" />
                    <span>💬 独立 IM 对话弹窗</span>
                  </Button>
                )}
              </div>

              <div className="space-y-2">
                <span className="text-[11px] text-slate-300 font-semibold font-sans block">
                  人工客服回复消息（发送后用户将直接在聊天窗口中实时看到）：
                </span>
                <Input
                  type="text"
                  value={humanCustomReply}
                  onChange={(e) => setHumanCustomReply(e.target.value)}
                  placeholder="输入向客户发送的人工回复（例如：您好！已为您查验，这笔退款为您加急处理中）..."
                  className="w-full bg-slate-950 text-xs py-2 border-slate-800 focus-visible:ring-indigo-500 text-slate-100 rounded-xl placeholder-slate-600"
                />
              </div>

              <div className="flex flex-col sm:flex-row gap-3 pt-2">
                <Button
                  onClick={async () => {
                    if (handleHumanReplyAction) {
                      const text =
                        humanCustomReply.trim() ||
                        "您好！人工客服专员已为您接管服务。请问有什么可以帮您？";
                      await handleHumanReplyAction(
                        selectedApproval.id,
                        text,
                        false,
                      );
                      setHumanCustomReply("");
                    } else {
                      await handleApprovalAction(
                        selectedApproval.id,
                        "approve",
                      );
                    }
                    setActiveTab("CHAT_DESK");
                  }}
                  disabled={isSubmitting}
                  className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl h-10 text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-lg shadow-indigo-600/20"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <MessageSquare className="h-4 w-4" />
                  )}
                  <span>💬 发送人工回复并保持接管</span>
                </Button>

                <Button
                  onClick={async () => {
                    if (handleHumanReplyAction) {
                      const text =
                        humanCustomReply.trim() ||
                        "人工客服为您服务完毕。现已为您重新对接 AI 智能助手！";
                      await handleHumanReplyAction(
                        selectedApproval.id,
                        text,
                        true,
                      );
                    } else {
                      await handleApprovalAction(
                        selectedApproval.id,
                        "approve",
                      );
                    }
                    setActiveTab("CHAT_DESK");
                  }}
                  disabled={isSubmitting}
                  variant="secondary"
                  className="flex-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl h-10 text-xs font-bold transition flex items-center justify-center space-x-1.5"
                >
                  <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                  <span>🏁 结束人工服务 (切回 AI)</span>
                </Button>

                <Button
                  onClick={async () => {
                    await handleApprovalAction(selectedApproval.id, "reject");
                    setActiveTab("CHAT_DESK");
                  }}
                  disabled={isSubmitting}
                  variant="destructive"
                  className="bg-rose-600 hover:bg-rose-500 text-white rounded-xl h-10 px-4 text-xs font-bold transition flex items-center justify-center space-x-1.5"
                >
                  <XCircle className="h-4 w-4" />
                  <span>拒绝转人工</span>
                </Button>
              </div>
            </div>
          ) : (
            /* 🛡️ 高危操作（如资金退款）标准核准/驳回工作台 */
            <div className="space-y-4 pt-4 border-t border-slate-800">
              {onOpenChatModal && (
                <div className="flex justify-end">
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => onOpenChatModal(selectedApproval)}
                    className="bg-indigo-600/30 hover:bg-indigo-600/50 border border-indigo-500/40 text-indigo-200 rounded-lg text-[11px] h-7 px-2.5 font-bold flex items-center gap-1 transition shadow-sm"
                  >
                    <MessageSquare className="h-3 w-3 text-indigo-400" />
                    <span>💬 独立 IM 对话弹窗</span>
                  </Button>
                </div>
              )}
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
                    await handleApprovalAction(actionId, "approve");
                    setActiveTab("CHAT_DESK");
                  }}
                  disabled={isSubmitting}
                  className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded-xl h-11 text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-lg shadow-emerald-600/10"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="h-4.5 w-4.5" />
                  )}
                  <span>核准通过此申请 (Approve)</span>
                </Button>
                <Button
                  onClick={async () => {
                    const actionId = selectedApproval.id;
                    await handleApprovalAction(actionId, "reject");
                    setActiveTab("CHAT_DESK");
                  }}
                  disabled={isSubmitting}
                  variant="destructive"
                  className="flex-1 bg-rose-600 hover:bg-rose-500 text-white rounded-xl h-11 text-xs font-bold transition flex items-center justify-center space-x-1.5 shadow-lg shadow-rose-600/10"
                >
                  {isSubmitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <XCircle className="h-4.5 w-4.5" />
                  )}
                  <span>驳回此高危动作 (Reject)</span>
                </Button>
              </div>
            </div>
          )
        ) : (
          <div className="p-4 bg-slate-900 border border-slate-850 rounded-xl space-y-1">
            <span className="text-[10px] text-slate-500 font-mono tracking-wider uppercase block">
              工单审计回执
            </span>
            <p className="text-xs text-slate-300 font-medium leading-relaxed font-sans">
              本工单已被管理员处理完成，处理决议：
              <strong
                className={`font-bold ${
                  selectedApproval.status === "approved" ||
                  selectedApproval.status === "resolved_by_human"
                    ? "text-emerald-400"
                    : "text-rose-400"
                }`}
              >
                {selectedApproval.status === "approved"
                  ? "已核准放行"
                  : selectedApproval.status === "resolved_by_human"
                    ? "已由人工客服接管并办结"
                    : selectedApproval.status === "rejected"
                      ? "已驳回动作"
                      : "已被系统自动超时拦截"}
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
