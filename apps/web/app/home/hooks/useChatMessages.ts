import { useCallback, useEffect, useRef, useState } from 'react';
import type { RunningDetail, TaskPlan } from 'types';
import { AgentStreamClient } from '../utils/agentStreamClient';
import { translateTaskPlan } from '../utils/translateTaskPlan';
import type { Message, UserSession } from './types';

interface UseChatMessagesProps {
  currentUser: UserSession | null;
  activeThreadId: string;
  fetchThreads: () => Promise<void>;
}

export function useChatMessages({ currentUser, activeThreadId, fetchThreads }: UseChatMessagesProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content:
        '您好！我是您的高级智能电商客服助理。基于 LangGraph 决策图、智能执行流以及多维度记忆系统，我能帮您自动化处理订单查询、快捷退款、库存核验或网页截图看板分析。今天有什么我可以帮您的？',
    },
  ]);
  const [input, setInput] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activePlan, setActivePlan] = useState<TaskPlan | null>(null);
  const [currentStepText, setCurrentStepText] = useState('');
  const [selectedScreenshot, setSelectedScreenshot] = useState<string | null>(null);
  const [tokensConsumed, setTokensConsumed] = useState<number>(0);
  const [runningDetails, setRunningDetails] = useState<RunningDetail[]>([]);

  const syncPollCountRef = useRef<number>(0);

  // Load past conversation records
  const loadHistory = useCallback(async (threadIdToLoad: string) => {
    if (!threadIdToLoad) return;
    try {
      const res = await fetch(`/api/chat/messages?threadId=${threadIdToLoad}`);
      const data = await res.json();
      if (data.success && data.messages && data.messages.length > 0) {
        setMessages((prev) => {
          const hasPendingLoader = prev.some((m) => m.isLoading || m.jobId === 'pending-job');
          if (hasPendingLoader) return prev;

          const currentSig = JSON.stringify(prev.map((m) => ({ role: m.role, content: m.content })));
          const newSig = JSON.stringify(
            data.messages.map((m: { role: string; content: string }) => ({
              role: m.role,
              content: m.content,
            })),
          );

          if (currentSig !== newSig) {
            return data.messages;
          }
          return prev;
        });
      }
    } catch (err) {
      console.warn('[History Restore] 无法加载物理数据库的历史记录: ', err);
    }
  }, []);

  // Sync activeThreadId changing to loading history
  useEffect(() => {
    if (activeThreadId) {
      loadHistory(activeThreadId);
    } else {
      setMessages([
        {
          role: 'assistant',
          content:
            '您好！我是您的高级智能电商客服助理。基于 LangGraph 决策图、智能执行流以及多维度记忆系统，我能帮您自动化处理订单查询、快捷退款、库存核验或网页截图看板分析。今天有什么我可以帮您的？',
        },
      ]);
    }
    setRunningDetails([]);
    setActivePlan(null);
    setCurrentStepText('');
  }, [activeThreadId, loadHistory]);

  const triggerStream = useCallback(
    async (jobId: string) => {
      setRunningDetails([]);
      const client = new AgentStreamClient(jobId);

      client.connect({
        onStatus: (data) => {
          if (data.tokens !== undefined) {
            setTokensConsumed(data.tokens);
          }
          if (data.message) {
            const msgStr = String(data.message);
            const zhMessage = msgStr;
            const nodeName = data.nodeName || 'system';

            setCurrentStepText(zhMessage);

            setRunningDetails((prev) => {
              const exists = prev.findIndex((log) => log.node === nodeName);
              if (exists !== -1) {
                const next = [...prev];
                const isProcessing = msgStr.includes('正在') || msgStr.includes('检测');
                next[exists] = {
                  node: nodeName,
                  desc: isProcessing ? msgStr : next[exists].desc || zhMessage,
                  resultText: !isProcessing ? msgStr : next[exists].resultText || '正在执行中...',
                };
                return next;
              }
              return [
                ...prev,
                {
                  node: nodeName,
                  desc: zhMessage,
                  resultText: '正在执行中...',
                },
              ];
            });
          }
          if (data.plan) {
            setActivePlan(translateTaskPlan(data.plan as any, false));
          }
        },
        onResult: (data) => {
          if (data.tokens !== undefined) {
            setTokensConsumed(data.tokens);
          }

          setRunningDetails((prev) =>
            prev.map((log) => {
              if (log.resultText === '正在执行中...') {
                return {
                  ...log,
                  resultText: '✅ 步骤已由有环图决策环成功履约。',
                };
              }
              return log;
            }),
          );

          setMessages((prev) => {
            const next = [...prev];
            const loaderIdx = next.findIndex((m) => m.jobId === jobId);
            if (loaderIdx !== -1) {
              next[loaderIdx] = {
                role: 'assistant',
                content: data.output || '',
                plan: data.taskPlan ? translateTaskPlan(data.taskPlan as any, true) : undefined,
                jobId,
              };
            }
            return next;
          });

          fetchThreads();
          setActivePlan(null);
          setCurrentStepText('');
          setIsSubmitting(false);
        },
        onError: (err) => {
          console.error('[useChatMessages] SSE Stream error:', err);
          setIsSubmitting(false);
          setCurrentStepText('');
          setActivePlan(null);
        },
      });
    },
    [fetchThreads],
  );

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isSubmitting || !activeThreadId || !currentUser) return;

    const userQuery = input;
    setInput('');
    setIsSubmitting(true);
    setTokensConsumed(0);

    const userMessage: Message = { role: 'user', content: userQuery };
    const loaderMessage: Message = {
      role: 'assistant',
      content: '',
      isLoading: true,
      jobId: 'pending-job',
    };

    setMessages((prev) => [...prev, userMessage, loaderMessage]);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userQuery,
          threadId: activeThreadId,
          userId: currentUser.id,
        }),
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || '创建执行链路失败');
      }

      if (data.isHumanActive) {
        setMessages((prev) => prev.filter((m) => m.jobId !== 'pending-job'));
        setIsSubmitting(false);
        await loadHistory(activeThreadId);
        return;
      }

      setMessages((prev) => prev.map((m) => (m.jobId === 'pending-job' ? { ...m, jobId: data.jobId } : m)));

      triggerStream(data.jobId);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.error(err);
      setMessages((prev) =>
        prev.map((m) =>
          m.jobId === 'pending-job'
            ? {
                role: 'assistant',
                content: `执行出错: ${errMsg || '内部处理异常，请重试'}`,
              }
            : m,
        ),
      );
      setIsSubmitting(false);
    }
  };

  return {
    messages,
    setMessages,
    input,
    setInput,
    isSubmitting,
    setIsSubmitting,
    activePlan,
    setActivePlan,
    currentStepText,
    setCurrentStepText,
    selectedScreenshot,
    setSelectedScreenshot,
    tokensConsumed,
    setTokensConsumed,
    runningDetails,
    setRunningDetails,
    syncPollCountRef,
    loadHistory,
    triggerStream,
    handleSend,
  };
}
