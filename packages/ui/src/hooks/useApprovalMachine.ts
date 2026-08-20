import { useCallback, useState } from 'react';

export interface ApprovalActionResult {
  success: boolean;
  error?: string;
  data?: unknown;
}

export interface ExecuteApprovalActionOptions {
  approvalId: string;
  action: 'approve' | 'reject' | 'cancel';
  rejectionReason?: string;
  apiEndpoint?: string;
}

export interface ExecuteHumanReplyOptions {
  approvalId: string;
  replyMessage: string;
  isFinish?: boolean;
  apiEndpoint?: string;
}

export function useApprovalMachine(defaultEndpoint = '/api/chat/approvals') {
  const [submittingActionId, setSubmittingActionId] = useState<string | null>(null);
  const [rejectionReasons, setRejectionReasons] = useState<Record<string, string>>({});

  const setRejectionReason = useCallback((approvalId: string, reason: string) => {
    setRejectionReasons((prev) => ({
      ...prev,
      [approvalId]: reason,
    }));
  }, []);

  const clearRejectionReason = useCallback((approvalId: string) => {
    setRejectionReasons((prev) => {
      const next = { ...prev };
      delete next[approvalId];
      return next;
    });
  }, []);

  const executeApprovalAction = useCallback(
    async ({
      approvalId,
      action,
      rejectionReason,
      apiEndpoint = defaultEndpoint,
    }: ExecuteApprovalActionOptions): Promise<ApprovalActionResult> => {
      setSubmittingActionId(approvalId);
      try {
        const reason = rejectionReason !== undefined ? rejectionReason : rejectionReasons[approvalId] || '';

        const res = await fetch(apiEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            approvalId,
            action,
            rejectionReason: action === 'reject' ? reason || '退款申请不符合政策要求。' : '',
          }),
        });

        const data = await res.json();
        if (data.success) {
          clearRejectionReason(approvalId);
          return { success: true, data };
        }
        return {
          success: false,
          error: data.error || '审批执行失败，请稍后重试',
        };
      } catch (err: unknown) {
        const errMsg = err instanceof Error ? err.message : String(err);
        return { success: false, error: `审批流恢复网络异常: ${errMsg}` };
      } finally {
        setSubmittingActionId(null);
      }
    },
    [defaultEndpoint, rejectionReasons, clearRejectionReason],
  );

  const executeHumanReplyAction = useCallback(
    async ({
      approvalId,
      replyMessage,
      isFinish = false,
      apiEndpoint = defaultEndpoint,
    }: ExecuteHumanReplyOptions): Promise<ApprovalActionResult> => {
      setSubmittingActionId(approvalId);
      try {
        const res = await fetch(apiEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            approvalId,
            action: isFinish ? 'human_finish' : 'human_message',
            humanReply: replyMessage,
            replyMessage,
            isFinish,
          }),
        });

        const data = await res.json();
        if (data.success) {
          return { success: true, data };
        }
        return {
          success: false,
          error: data.error || '人工消息投递失败',
        };
      } catch (err: unknown) {
        const errMsg = err instanceof Error ? err.message : String(err);
        return { success: false, error: `人工消息投递异常: ${errMsg}` };
      } finally {
        setSubmittingActionId(null);
      }
    },
    [defaultEndpoint],
  );

  return {
    submittingActionId,
    setSubmittingActionId,
    rejectionReasons,
    setRejectionReasons,
    setRejectionReason,
    clearRejectionReason,
    executeApprovalAction,
    executeHumanReplyAction,
  };
}
