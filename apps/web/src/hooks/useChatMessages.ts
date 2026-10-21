import { useCallback, useEffect, useRef, useState } from 'react';
import type { RunningDetail, TaskPlan } from 'types';
import { AgentStreamClient } from '../lib/agentStreamClient';
import { interruptGeneration, markInterrupted } from '../lib/interruptGeneration';
import { quotaBubbleText } from '../lib/quotaGuidance';
import { translateTaskPlan } from '../lib/translateTaskPlan';
import type { Message, UserSession } from './types';
import { TOKEN_KEY } from './useAuth';

interface UseChatMessagesProps {
  currentUser: UserSession | null;
  activeThreadId: string;
  activeBusinessId?: string;
  fetchThreads: () => Promise<void>;
}

export function useChatMessages({ currentUser, activeThreadId, activeBusinessId, fetchThreads }: UseChatMessagesProps) {
  // 欢迎语服务端权威(new-user-onboarding F):建线程时网关已按租户 onboarding_config
  // 落 welcome assistant 行(带入口卡),前端不再本地伪造默认欢迎语
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activePlan, setActivePlan] = useState<TaskPlan | null>(null);
  const [currentStepText, setCurrentStepText] = useState('');
  const [selectedScreenshot, setSelectedScreenshot] = useState<string | null>(null);
  const [tokensConsumed, setTokensConsumed] = useState<number>(0);
  const [runningDetails, setRunningDetails] = useState<RunningDetail[]>([]);
  // S2a:打断在途回答 —— isInterrupting 驱动「正在停止…」态(按钮禁用防重),
  // activeJobIdRef 供 stopGeneration 取当前作业
  const [isInterrupting, setIsInterrupting] = useState(false);
  const isInterruptingRef = useRef(false);

  // S2a(评审收口):打断态复位三连收敛单点,严禁散写漂移
  const resetInterruptState = useCallback(() => {
    isInterruptingRef.current = false;
    setIsInterrupting(false);
    activeJobIdRef.current = '';
  }, []);

  const syncPollCountRef = useRef<number>(0);
  const activeThreadIdRef = useRef<string>(activeThreadId);
  const activeJobIdRef = useRef<string>('');

  useEffect(() => {
    activeThreadIdRef.current = activeThreadId;
  }, [activeThreadId]);

  // Load past conversation records
  const loadHistory = useCallback(async (threadIdToLoad: string, force = false) => {
    if (!threadIdToLoad) return;
    try {
      const res = await fetch(`/api/chat/messages?threadId=${threadIdToLoad}`);
      const data = await res.json();
      // 🛡️ 竞态防护：如果当前用户已经切换到了其他会话，丢弃本次迟到的历史响应
      if (threadIdToLoad !== activeThreadIdRef.current) {
        return;
      }
      if (data.success && Array.isArray(data.messages)) {
        // 空历史即空时间线:welcome 行由建线程服务端写入,此处不再伪造兜底欢迎语
        const fullMessages: Message[] = data.messages;

        setMessages((prev) => {
          // 如果用户已经切换了会话，立即忽略
          if (threadIdToLoad !== activeThreadIdRef.current) {
            return prev;
          }

          if (!force) {
            const hasPendingLoader = prev.some((m) => m.isLoading || m.jobId === 'pending-job');
            if (hasPendingLoader) return prev;
          }

          return fullMessages;
        });
      }
    } catch (err) {
      console.warn('[History Restore] 无法加载物理数据库的历史记录: ', err);
    }
  }, []);

  // Sync activeThreadId changing to loading history
  useEffect(() => {
    activeThreadIdRef.current = activeThreadId;
    setTokensConsumed(0);
    setRunningDetails([]);
    setActivePlan(null);
    setCurrentStepText('');
    setIsSubmitting(false);
    resetInterruptState();

    // 🚀 切换或新建会话时，立即先清空界面消息,彻底消除旧会话视觉残留与历史穿透;
    // 欢迎行随 loadHistory 从服务端恢复(建线程时已落库)
    setMessages([]);

    if (activeThreadId) {
      loadHistory(activeThreadId);
    }
  }, [activeThreadId, loadHistory, resetInterruptState]);

  // quotaHint(2026-10-21 配额闸):POST 信封的 quotaCode 增量键(仅配额拒时
  // 出现)—— 正常路径由 SSE result 帧(output+quotaCode)渲染引导气泡;流
  // 若中断,凭信封码仍能按码给引导文案,不谎称「未能完成,请重新发送」。
  const triggerStream = useCallback(
    async (jobId: string, quotaHint = '') => {
      setRunningDetails([]);
      const client = new AgentStreamClient(jobId);

      // S2a(评审收口):终局复位 —— 打断态无条件复位;活跃作业登记仅在
      // 「仍是当前作业」时清空。切线程 mid-stream 后旧流的晚到终局帧
      // (正常/interrupted/onError 三臂同断言)严禁清掉新作业的登记,
      // 否则新线程的停止按钮静默失效。
      const settleStreamTerminal = () => {
        isInterruptingRef.current = false;
        setIsInterrupting(false);
        if (jobId === activeJobIdRef.current) {
          activeJobIdRef.current = '';
        }
      };

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

          // S2a:用户打断的终局帧(引擎 S2c interrupted 收口)—— 部分态诚实
          // 标注「已停止」,严禁走正常完成路径假装修完
          if (data.interrupted) {
            setMessages((prev) => markInterrupted(prev, jobId, data.output || ''));
            setRunningDetails((prev) =>
              prev.map((log) => (log.resultText === '正在执行中...' ? { ...log, resultText: '⏹ 已被用户停止' } : log)),
            );
            settleStreamTerminal();
            fetchThreads();
            setActivePlan(null);
            setCurrentStepText('');
            setIsSubmitting(false);
            return;
          }

          // 配额拒终局帧(2026-10-21 配额闸):result 帧携 quotaCode 增量键,
          // data.output 为后端权威文案 —— 业务拒绝非系统故障:不发「成功履约」
          // 步骤标注、不落 plan;气泡 = output 照实 + 固定操作建议(文案映射
          // 收口 lib/quotaGuidance,诚实律:不编造剩余额度)。
          if (data.quotaCode) {
            const quotaCode = data.quotaCode;
            setMessages((prev) => {
              const next = [...prev];
              const loaderIdx = next.findIndex((m) => m.jobId === jobId);
              if (loaderIdx !== -1) {
                next[loaderIdx] = {
                  role: 'assistant',
                  content: quotaBubbleText(quotaCode, data.output || ''),
                  jobId,
                };
              }
              return next;
            });
            fetchThreads();
            setActivePlan(null);
            setCurrentStepText('');
            setIsSubmitting(false);
            settleStreamTerminal();
            return;
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
                cards: data.cards,
                jobId,
              };
            }
            return next;
          });

          fetchThreads();
          setActivePlan(null);
          setCurrentStepText('');
          setIsSubmitting(false);
          settleStreamTerminal();
        },
        onError: (err) => {
          console.error('[useChatMessages] SSE Stream error:', err);
          // 流中断诚实降级(2026-09-30 夜审):AgentStreamClient 的 error 监听
          // 已显式 close(),不会自动重连 —— 加载气泡必须就地转错误文案,
          // 否则「打字中」永挂且无任何提示(POST 失败路径同款处理)。
          // 配额拒已定局(信封 quotaHint 在案)而流中断:按码给引导文案,
          // 不谎称「未能完成可重发」(该回合已被拒绝,重发仍会被拒)。
          setMessages((prev) =>
            prev.map((m) =>
              m.isLoading && m.jobId === jobId
                ? {
                    role: 'assistant',
                    content: quotaHint
                      ? quotaBubbleText(quotaHint, '')
                      : '连接中断，本次回复未能完成，请重新发送或稍后重试。',
                  }
                : m,
            ),
          );
          setIsSubmitting(false);
          setCurrentStepText('');
          setActivePlan(null);
          settleStreamTerminal();
        },
      });
    },
    [fetchThreads],
  );

  // S2a:停止生成 —— 消费网关取消契约(03 号票);404=作业已结束(竞态,
  // result 帧即将收口,无需本地态),其余失败保持 interrupting 态由 result/
  // 错误帧兜底收口;按钮禁用防重,重复点击天然幂等
  const stopGeneration = useCallback(async () => {
    const jobId = activeJobIdRef.current;
    if (!jobId || !currentUser || isInterruptingRef.current) return;
    setIsInterrupting(true);
    isInterruptingRef.current = true;
    const outcome = await interruptGeneration({
      jobId,
      userId: currentUser.id,
      businessId: activeBusinessId,
    });
    if (!outcome.ok && outcome.status === 404) {
      // 作业已结束(竞态):result 帧即将/已经收口,撤本地打断态;
      // 登记仅在仍是本作业时清(与终局臂同守卫)
      isInterruptingRef.current = false;
      setIsInterrupting(false);
      if (activeJobIdRef.current === jobId) activeJobIdRef.current = '';
    }
  }, [currentUser, activeBusinessId]);

  const handleSend = async (e?: React.FormEvent, customText?: string, customImages?: string[]) => {
    if (e) e.preventDefault();
    const textToSend = (customText !== undefined ? customText : input).trim();
    const imagesToSend = customImages || [];

    if ((!textToSend && imagesToSend.length === 0) || isSubmitting || !activeThreadId || !currentUser) return;

    const userQuery = textToSend || (imagesToSend.length > 0 ? '请查看我上传的图片' : '');
    setInput('');
    setIsSubmitting(true);
    setTokensConsumed(0);

    const userMessage: Message = {
      id: `opt_user_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      role: 'user',
      content: userQuery,
      imageUrls: imagesToSend.length > 0 ? imagesToSend : undefined,
    };
    const loaderMessage: Message = {
      id: `opt_loader_${Date.now()}`,
      role: 'assistant',
      content: '',
      isLoading: true,
      jobId: 'pending-job',
    };

    setMessages((prev) => [...prev, userMessage, loaderMessage]);

    try {
      // 配额闸 Q5b(2026-10-21):/api/chat 强制 JWT —— 无/坏 token 401
      // {success:false,error};body.userId 与 JWT sub 不一致 403。token 从
      // localStorage 单点读入(useAuth TOKEN_KEY);currentUser.id 经
      // /api/auth/me 静默自愈即 JWT sub,自报字段仅作交叉校验。
      const token = typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null;
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: userQuery,
          threadId: activeThreadId,
          userId: currentUser.id,
          businessId: activeBusinessId,
          imageUrls: imagesToSend.length > 0 ? imagesToSend : undefined,
        }),
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || '创建执行链路失败');
      }

      if (data.isHumanActive) {
        setIsSubmitting(false);
        setMessages((prev) => prev.filter((m) => !m.isLoading && m.jobId !== 'pending-job'));
        await loadHistory(activeThreadId, true);
        return;
      }

      setMessages((prev) => prev.map((m) => (m.jobId === 'pending-job' ? { ...m, jobId: data.jobId } : m)));

      // S2a:登记活跃作业供 stopGeneration 取用
      activeJobIdRef.current = data.jobId;
      // 配额拒信封增量键(仅拒时出现,jobId 同有值):作 hint 传入,流中断
      // 时仍能按码给引导;正常路径由 SSE result 帧 output+quotaCode 渲染
      triggerStream(data.jobId, typeof data.quotaCode === 'string' ? data.quotaCode : '');
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
    stopGeneration,
    isInterrupting,
  };
}
