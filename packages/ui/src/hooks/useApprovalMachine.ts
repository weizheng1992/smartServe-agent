import { useCallback, useMemo, useState } from 'react';

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
  /** 核准人契约(admin-readiness 01):调用方声明身份;缺省由网关按调用面角色兜底 */
  actor?: string;
  actorRole?: 'platform_admin' | 'merchant_operator' | 'system';
  /** 02 安全先行:chat 面顾客动作须携会话属主 userId 供线程归属绑定 */
  userId?: string;
}

export interface ExecuteHumanReplyOptions {
  approvalId: string;
  replyMessage: string;
  isFinish?: boolean;
  apiEndpoint?: string;
}

/** 最小 fetch 结构类型:注入方无需满足完整 typeof fetch(如 preconnect)。 */
export type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface ApprovalMachineOptions {
  /** 注入应用层 fetch(如带 Authorization 的包装);缺省全局 fetch。
   *  ui 包零依赖不变量:鉴权等横切逻辑由调用方注入,本包不 import 应用层代码。 */
  fetcher?: FetchLike;
}

export function useApprovalMachine(defaultEndpoint = '/api/chat/approvals', options?: ApprovalMachineOptions) {
  const [submittingActionId, setSubmittingActionId] = useState<string | null>(null);
  const [rejectionReasons, setRejectionReasons] = useState<Record<string, string>>({});
  const injectedFetch = options?.fetcher;
  // bind(globalThis):裸 fetch 引用在部分环境下丢失窗口上下文会 Illegal invocation
  const doFetch = useMemo(() => injectedFetch ?? fetch.bind(globalThis), [injectedFetch]);

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
      actor,
      actorRole,
      userId,
    }: ExecuteApprovalActionOptions): Promise<ApprovalActionResult> => {
      setSubmittingActionId(approvalId);
      try {
        const reason = rejectionReason !== undefined ? rejectionReason : rejectionReasons[approvalId] || '';

        const res = await doFetch(apiEndpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            approvalId,
            action,
            rejectionReason: action === 'reject' ? reason || '退款申请不符合政策要求。' : '',
            ...(actor ? { actor } : {}),
            ...(actorRole ? { actorRole } : {}),
            ...(userId ? { userId } : {}),
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
    [defaultEndpoint, rejectionReasons, clearRejectionReason, doFetch],
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
        const res = await doFetch(apiEndpoint, {
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
    [defaultEndpoint, doFetch],
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
