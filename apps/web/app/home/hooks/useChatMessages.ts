import { useCallback, useEffect, useRef, useState } from "react";
import type { RunningDetail, TaskPlan } from "types";
import { AgentStreamClient } from "../utils/agentStreamClient";
import { translateTaskPlan } from "../utils/translateTaskPlan";
import type { Message, UserSession } from "./types";

export const DEFAULT_ASSISTANT_MESSAGE: Message = {
  id: "default_welcome",
  role: "assistant",
  content:
    "您好！我是您的高级智能电商客服助理。基于 LangGraph 决策图、智能执行流以及多维度记忆系统，我能帮您自动化处理订单查询、快捷退款、库存核验或网页截图看板分析。今天有什么我可以帮您的？",
};

interface UseChatMessagesProps {
  currentUser: UserSession | null;
  activeThreadId: string;
  activeBusinessId?: string;
  fetchThreads: () => Promise<void>;
}

export function useChatMessages({
  currentUser,
  activeThreadId,
  activeBusinessId,
  fetchThreads,
}: UseChatMessagesProps) {
  const [messages, setMessages] = useState<Message[]>([
    DEFAULT_ASSISTANT_MESSAGE,
  ]);
  const [input, setInput] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activePlan, setActivePlan] = useState<TaskPlan | null>(null);
  const [currentStepText, setCurrentStepText] = useState("");
  const [selectedScreenshot, setSelectedScreenshot] = useState<string | null>(
    null,
  );
  const [tokensConsumed, setTokensConsumed] = useState<number>(0);
  const [runningDetails, setRunningDetails] = useState<RunningDetail[]>([]);

  const syncPollCountRef = useRef<number>(0);
  const activeThreadIdRef = useRef<string>(activeThreadId);

  useEffect(() => {
    activeThreadIdRef.current = activeThreadId;
  }, [activeThreadId]);

  // Load past conversation records
  const loadHistory = useCallback(
    async (threadIdToLoad: string, force = false) => {
      if (!threadIdToLoad) return;
      try {
        const res = await fetch(
          `/api/chat/messages?threadId=${threadIdToLoad}`,
        );
        const data = await res.json();
        // 🛡️ 竞态防护：如果当前用户已经切换到了其他会话，丢弃本次迟到的历史响应
        if (threadIdToLoad !== activeThreadIdRef.current) {
          return;
        }
        if (data.success && Array.isArray(data.messages)) {
          const fullMessages: Message[] =
            data.messages.length > 0
              ? data.messages
              : [DEFAULT_ASSISTANT_MESSAGE];

          setMessages((prev) => {
            // 如果用户已经切换了会话，立即忽略
            if (threadIdToLoad !== activeThreadIdRef.current) {
              return prev;
            }

            if (!force) {
              const hasPendingLoader = prev.some(
                (m) => m.isLoading || m.jobId === "pending-job",
              );
              if (hasPendingLoader) return prev;
            }

            return fullMessages;
          });
        }
      } catch (err) {
        console.warn("[History Restore] 无法加载物理数据库的历史记录: ", err);
      }
    },
    [],
  );

  // Sync activeThreadId changing to loading history
  useEffect(() => {
    activeThreadIdRef.current = activeThreadId;
    setTokensConsumed(0);
    setRunningDetails([]);
    setActivePlan(null);
    setCurrentStepText("");
    setIsSubmitting(false);

    // 🚀 切换或新建会话时，立即先重置界面消息为初始欢迎语，彻底消除旧会话视觉残留与历史穿透
    setMessages([DEFAULT_ASSISTANT_MESSAGE]);

    if (activeThreadId) {
      loadHistory(activeThreadId);
    }
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
            const nodeName = data.nodeName || "system";

            setCurrentStepText(zhMessage);

            setRunningDetails((prev) => {
              const exists = prev.findIndex((log) => log.node === nodeName);
              if (exists !== -1) {
                const next = [...prev];
                const isProcessing =
                  msgStr.includes("正在") || msgStr.includes("检测");
                next[exists] = {
                  node: nodeName,
                  desc: isProcessing ? msgStr : next[exists].desc || zhMessage,
                  resultText: !isProcessing
                    ? msgStr
                    : next[exists].resultText || "正在执行中...",
                };
                return next;
              }
              return [
                ...prev,
                {
                  node: nodeName,
                  desc: zhMessage,
                  resultText: "正在执行中...",
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
              if (log.resultText === "正在执行中...") {
                return {
                  ...log,
                  resultText: "✅ 步骤已由有环图决策环成功履约。",
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
                role: "assistant",
                content: data.output || "",
                plan: data.taskPlan
                  ? translateTaskPlan(data.taskPlan as any, true)
                  : undefined,
                cards: data.cards,
                jobId,
              };
            }
            return next;
          });

          fetchThreads();
          setActivePlan(null);
          setCurrentStepText("");
          setIsSubmitting(false);
        },
        onError: (err) => {
          console.error("[useChatMessages] SSE Stream error:", err);
          setIsSubmitting(false);
          setCurrentStepText("");
          setActivePlan(null);
        },
      });
    },
    [fetchThreads],
  );

  const handleSend = async (
    e?: React.FormEvent,
    customText?: string,
    customImages?: string[],
  ) => {
    if (e) e.preventDefault();
    const textToSend = (customText !== undefined ? customText : input).trim();
    const imagesToSend = customImages || [];

    if (
      (!textToSend && imagesToSend.length === 0) ||
      isSubmitting ||
      !activeThreadId ||
      !currentUser
    )
      return;

    const userQuery =
      textToSend || (imagesToSend.length > 0 ? "请查看我上传的图片" : "");
    setInput("");
    setIsSubmitting(true);
    setTokensConsumed(0);

    const userMessage: Message = {
      id: `opt_user_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      role: "user",
      content: userQuery,
      imageUrls: imagesToSend.length > 0 ? imagesToSend : undefined,
    };
    const loaderMessage: Message = {
      id: `opt_loader_${Date.now()}`,
      role: "assistant",
      content: "",
      isLoading: true,
      jobId: "pending-job",
    };

    setMessages((prev) => [...prev, userMessage, loaderMessage]);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
        throw new Error(data.error || "创建执行链路失败");
      }

      if (data.isHumanActive) {
        setIsSubmitting(false);
        setMessages((prev) =>
          prev.filter((m) => !m.isLoading && m.jobId !== "pending-job"),
        );
        await loadHistory(activeThreadId, true);
        return;
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.jobId === "pending-job" ? { ...m, jobId: data.jobId } : m,
        ),
      );

      triggerStream(data.jobId);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.error(err);
      setMessages((prev) =>
        prev.map((m) =>
          m.jobId === "pending-job"
            ? {
                role: "assistant",
                content: `执行出错: ${errMsg || "内部处理异常，请重试"}`,
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
