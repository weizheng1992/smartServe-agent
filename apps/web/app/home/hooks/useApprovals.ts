import { useEffect, useRef, useState } from 'react';
import type { PendingApprovalRecord } from 'types';
import { useApprovalMachine } from 'ui';
import type { Message, UserSession } from './types';

interface UseApprovalsProps {
  currentUser: UserSession | null;
  activeThreadId: string;
  loadHistory: (threadId: string) => Promise<void>;
  fetchThreads: () => Promise<void>;
  syncPollCountRef: React.MutableRefObject<number>;
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  setIsSubmitting: React.Dispatch<React.SetStateAction<boolean>>;
  triggerStream: (jobId: string) => Promise<void>;
}

export function useApprovals({
  currentUser,
  activeThreadId,
  loadHistory,
  fetchThreads,
  syncPollCountRef,
  setMessages,
  setIsSubmitting,
  triggerStream,
}: UseApprovalsProps) {
  const [allApprovals, setAllApprovals] = useState<any[]>([]);
  const [pendingApprovalsList, setPendingApprovalsList] = useState<any[]>([]);
  const [rejectionInput, setRejectionReason] = useState('');
  const [activeTab, setActiveTab] = useState<'CHAT_DESK' | 'AUDIT_DESK'>('CHAT_DESK');
  const [selectedApprovalId, setSelectedApprovalId] = useState<string | null>(null);
  const [auditFilter, setAuditFilter] = useState<'ALL' | 'WAITING' | 'APPROVED' | 'REJECTED' | 'EXPIRED'>('WAITING');

  const [activeChatApproval, setActiveChatApproval] = useState<PendingApprovalRecord | null>(null);

  const lastApprovalsStateRef = useRef<Record<string, string>>({});
  const { executeApprovalAction, executeHumanReplyAction } = useApprovalMachine();

  // 1. 周期性轮询获取与当前 ThreadID 相关且未审批的工单，并安全检测人机审核流程恢复
  useEffect(() => {
    // 切换会话时，安全重置多轮静默同步计数器与驳回原因，防止历史残留跨会话触发
    syncPollCountRef.current = 0;
    setRejectionReason('');

    // 立即响应 activeThreadId 变更，从已缓存的 allApprovals 中同步过滤当前线程待审批工单
    if (activeThreadId) {
      setPendingApprovalsList((prev) => {
        // 先快速清除非当前会话的工单，避免右侧面板短暂展示上一个会话的审批卡片
        return prev.filter((a: PendingApprovalRecord) => a.threadId === activeThreadId && a.status === 'waiting');
      });
    } else {
      setPendingApprovalsList([]);
    }

    const fetchApprovals = async () => {
      try {
        const res = await fetch('/api/chat/approvals');
        const data = await res.json();
        if (data.success && data.approvals) {
          setAllApprovals(data.approvals); // 全量存入大盘状态
          if (activeThreadId) {
            const activeApprovals = data.approvals.filter(
              (a: PendingApprovalRecord) => a.threadId === activeThreadId && a.status === 'waiting',
            );
            setPendingApprovalsList(activeApprovals);

            // 🎧 如果当前会话存在处于 waiting 状态的人工客服工单，说明处于人工实时 IM 对话中，
            // 每次轮询静默拉取一次最新消息，确保用户与客服双方的对话内容即时刷新呈现！
            const isHumanActive = activeApprovals.some(
              (a: PendingApprovalRecord) => a.actionType?.includes('human') || a.actionType?.includes('escalat'),
            );
            if (isHumanActive) {
              loadHistory(activeThreadId);
            }

            // 🧠 审批流防脱节自动载入感应器：
            // 如果上一次状态记录中存在该 thread 的某个工单且状态为 waiting，而新拉取的数据中该工单状态变为了 approved / rejected / cancelled / expired，
            // 说明该审批任务刚刚获得了决策解决。我们将触发连续 6 次的多轮高灵敏轮询，确保在后台 Agent（约耗时 2-5s）执行完结并写盘后，物理刷新出最新的最终消息！
            let stateChanged = false;
            const currentStatuses: Record<string, string> = {};

            for (const app of data.approvals) {
              if (app.threadId === activeThreadId) {
                currentStatuses[app.id] = app.status;
                const prevStatus = lastApprovalsStateRef.current[app.id];
                if (prevStatus === 'waiting' && app.status !== 'waiting') {
                  stateChanged = true;
                }
              }
            }

            lastApprovalsStateRef.current = {
              ...lastApprovalsStateRef.current,
              ...currentStatuses,
            };

            if (stateChanged) {
              console.log(
                '[HITL Sync Detector] 🩺 Detected active thread approval status change! Initiating multi-turn polling (6 turns) to wait for agent response.',
              );
              syncPollCountRef.current = 6; // 连续 6 次（共 12 秒）高敏捷静默刷新
              loadHistory(activeThreadId);
              fetchThreads();
            } else if (syncPollCountRef.current > 0) {
              syncPollCountRef.current -= 1;
              console.log(
                `[HITL Sync Detector] ⏳ Continuing multi-turn polling. Remaining turns: ${syncPollCountRef.current}`,
              );
              loadHistory(activeThreadId);
              fetchThreads();
            }
          } else {
            setPendingApprovalsList([]);
          }
        }
      } catch (err) {
        console.error('Failed to fetch approvals:', err);
      }
    };

    fetchApprovals();
    const intervalId = setInterval(fetchApprovals, 2000); // 2秒轮询一次，高敏捷反馈！

    return () => clearInterval(intervalId);
  }, [activeThreadId, loadHistory, fetchThreads, syncPollCountRef]);

  // 2. 提交管理员审批决议（Approved / Rejected）并恢复 Agent 决策执行
  const handleApprovalAction = async (approvalId: string, action: 'approve' | 'reject') => {
    setIsSubmitting(true);
    setPendingApprovalsList([]); // 立即清空，提供瞬时界面反馈

    const resumeLoaderMsg: Message = {
      role: 'assistant',
      content: '',
      isLoading: true,
      jobId: 'resume-pending-job',
    };
    setMessages((prev) => [...prev, resumeLoaderMsg]);

    try {
      const result = await executeApprovalAction({
        approvalId,
        action,
        rejectionReason: rejectionInput,
      });

      const data = result.data as any;
      if (result.success) {
        setRejectionReason(''); // 清空拒绝文本
        if (data?.jobId) {
          setMessages((prev) => prev.map((m) => (m.jobId === 'resume-pending-job' ? { ...m, jobId: data.jobId } : m)));
          // 重建 SSE 物理通道，无缝订阅新触发的恢复执行流
          await triggerStream(data.jobId);
        } else {
          // 人工接管决议（无需后台 workflow 回调，直接同步本地会话）
          setMessages((prev) => prev.filter((m) => m.jobId !== 'resume-pending-job'));
          setIsSubmitting(false);
          await loadHistory(activeThreadId);
          await fetchThreads();
        }
      } else {
        throw new Error(result.error || '审批决议提交失败');
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.error(err);
      setMessages((prev) =>
        prev.map((m) =>
          m.jobId === 'resume-pending-job'
            ? {
                role: 'assistant',
                content: `审批流恢复出错: ${errMsg || '内部处理异常'}`,
              }
            : m,
        ),
      );
      setIsSubmitting(false);
    }
  };

  // 3. 客服在工作台直接向用户发送人工 IM 回复消息或结束人工接管
  const handleHumanReplyAction = async (approvalId: string, replyMessage: string, isFinish = false) => {
    setIsSubmitting(true);
    try {
      const result = await executeHumanReplyAction({
        approvalId,
        replyMessage,
        isFinish,
      });

      if (result.success) {
        setRejectionReason('');
        await loadHistory(activeThreadId);
        await fetchThreads();
        return result.data;
      }
      throw new Error(result.error || '人工消息投递失败');
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.error('[Human Reply Error]:', err);
      alert(`人工消息投递异常: ${errMsg}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  // 4. 主动发起对指定 Thread 会话的实时人工接管
  const startActiveTakeover = async (threadId?: string) => {
    const targetThreadId = threadId || activeThreadId || 'default_thread';
    setIsSubmitting(true);
    try {
      const res = await fetch('/api/chat/approvals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'start_human_takeover',
          threadId: targetThreadId,
        }),
      });
      const data = await res.json();
      if (data.success && data.approval) {
        setActiveChatApproval(data.approval);
        await loadHistory(targetThreadId);
        await fetchThreads();
        return data.approval as PendingApprovalRecord;
      }
      throw new Error(data.error || '发起主动接管失败');
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.error('[Start Active Takeover Error]:', err);
      alert(`发起人工接管异常: ${errMsg}`);
      return null;
    } finally {
      setIsSubmitting(false);
    }
  };

  return {
    allApprovals,
    setAllApprovals,
    pendingApprovalsList,
    setPendingApprovalsList,
    rejectionInput,
    setRejectionReason,
    activeTab,
    setActiveTab,
    selectedApprovalId,
    setSelectedApprovalId,
    auditFilter,
    setAuditFilter,
    activeChatApproval,
    setActiveChatApproval,
    startActiveTakeover,
    handleApprovalAction,
    handleHumanReplyAction,
  };
}
