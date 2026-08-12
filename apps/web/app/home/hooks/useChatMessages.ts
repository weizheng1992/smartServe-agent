import { useCallback, useEffect, useRef, useState } from "react";
import type { SubTask } from "types";
import type { Message, TaskPlan, UserSession } from "./types";

interface UseChatMessagesProps {
  currentUser: UserSession | null;
  activeThreadId: string;
  fetchThreads: () => Promise<void>;
}

export function useChatMessages({
  currentUser,
  activeThreadId,
  fetchThreads,
}: UseChatMessagesProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "您好！我是您的高级智能电商客服助理。基于 LangGraph 决策图、智能执行流以及多维度记忆系统，我能帮您自动化处理订单查询、快捷退款、库存核验或网页截图看板分析。今天有什么我可以帮您的？",
    },
  ]);
  const [input, setInput] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [activePlan, setActivePlan] = useState<TaskPlan | null>(null);
  const [currentStepText, setCurrentStepText] = useState("");
  const [selectedScreenshot, setSelectedScreenshot] = useState<string | null>(
    null,
  );
  const [tokensConsumed, setTokensConsumed] = useState<number>(0);
  const [runningDetails, setRunningDetails] = useState<
    { node: string; desc: string; resultText: string }[]
  >([]);

  const syncPollCountRef = useRef<number>(0);

  // Load past conversation records
  const loadHistory = useCallback(async (threadIdToLoad: string) => {
    if (!threadIdToLoad) return;
    try {
      const res = await fetch(`/api/chat/messages?threadId=${threadIdToLoad}`);
      const data = await res.json();
      if (data.success && data.messages && data.messages.length > 0) {
        setMessages((prev) => {
          // 正在等待 AI 节点响应或具有 loading 状态时，暂不覆盖本地 state
          const hasPendingLoader = prev.some(
            (m) => m.isLoading || m.jobId === "pending-job",
          );
          if (hasPendingLoader) return prev;

          const currentSig = JSON.stringify(
            prev.map((m) => ({ role: m.role, content: m.content })),
          );
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
      console.warn("[History Restore] 无法加载物理数据库的历史记录: ", err);
    }
  }, []);

  // Sync activeThreadId changing to loading history
  useEffect(() => {
    if (activeThreadId) {
      loadHistory(activeThreadId);
    } else {
      setMessages([
        {
          role: "assistant",
          content:
            "您好！我是您的高级智能电商客服助理。基于 LangGraph 决策图、智能执行流以及多维度记忆系统，我能帮您自动化处理订单查询、快捷退款、库存核验或网页截图看板分析。今天有什么我可以帮您的？",
        },
      ]);
    }
    // Safe reset of details & plan on thread switch
    setRunningDetails([]);
    setActivePlan(null);
    setCurrentStepText("");
  }, [activeThreadId, loadHistory]);

  const triggerStream = useCallback(
    async (jobId: string) => {
      try {
        const eventSource = new EventSource(`/api/chat/${jobId}/stream`);
        setRunningDetails([]); // Reset logger

        eventSource.addEventListener("status", (event: MessageEvent) => {
          const data = JSON.parse(event.data);
          if (data.tokens !== undefined) {
            setTokensConsumed(data.tokens);
          }
          if (data.message) {
            const zhMessage = data.message;
            let nodeName = data.node || "system";

            if (data.node === "triage") {
              nodeName = "Triage 节点";
            } else if (data.node === "planner") {
              nodeName = "Planner 节点";
            } else if (data.node === "executor") {
              nodeName = "Executor 节点";
            } else if (data.node === "validator") {
              nodeName = "Validator 节点";
            }

            setCurrentStepText(zhMessage);

            setRunningDetails((prev) => {
              const exists = prev.findIndex((log) => log.node === nodeName);
              if (exists !== -1) {
                const next = [...prev];
                next[exists] = {
                  node: nodeName,
                  desc:
                    data.message.includes("正在") ||
                    data.message.includes("检测")
                      ? data.message
                      : next[exists].desc,
                  resultText:
                    !data.message.includes("正在") &&
                    !data.message.includes("检测")
                      ? data.message
                      : next[exists].resultText,
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
            const zhSubtasks = data.plan.subtasks.map((st: SubTask) => {
              let zhDesc = st.description;
              const descLower = st.description.toLowerCase();
              if (
                descLower.includes("order status") ||
                descLower.includes("getorderstatus") ||
                descLower.includes("shipping status") ||
                descLower.includes("order")
              ) {
                zhDesc = "调起 getOrderStatus 接口查询订单最新物理物流详情";
              } else if (
                descLower.includes("screenshot") ||
                descLower.includes("takescreenshot")
              ) {
                zhDesc = "调起 takeScreenshot 看板截图工具进行界面快照核验";
              } else if (
                descLower.includes("refund") ||
                descLower.includes("processrefund")
              ) {
                zhDesc = "触发 processRefund 快速退款物理工作流";
              } else if (descLower.includes("extract")) {
                zhDesc = "智能捕获并定位文本中的业务关键字段与参数";
              } else if (
                descLower.includes("inform") ||
                descLower.includes("communicate") ||
                descLower.includes("tell")
              ) {
                zhDesc = "通过大模型提炼汇总信息反馈给用户";
              }
              return { ...st, description: zhDesc };
            });
            setActivePlan({
              ...data.plan,
              goal:
                data.plan.goal.includes("Fulfill") ||
                data.plan.goal.includes("Address")
                  ? "全自动履行客户业务及工具链诉求"
                  : data.plan.goal,
              subtasks: zhSubtasks,
            });
          }
        });

        eventSource.addEventListener("result", (event: MessageEvent) => {
          const data = JSON.parse(event.data);
          if (data.tokens !== undefined) {
            setTokensConsumed(data.tokens);
          }
          eventSource.close();

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
                content: data.output,
                plan: data.taskPlan
                  ? {
                      ...data.taskPlan,
                      goal: "自动化履行客户业务诉求",
                      subtasks: data.taskPlan.subtasks.map((sub: SubTask) => {
                        let zhDesc = sub.description;
                        const descLower = sub.description.toLowerCase();
                        if (descLower.includes("extract")) {
                          zhDesc = "从用户文本中智能提取业务参数与实体 ID";
                        } else if (
                          descLower.includes("getorderstatus") ||
                          descLower.includes("order status") ||
                          descLower.includes("shipping status") ||
                          descLower.includes("order")
                        ) {
                          zhDesc =
                            "成功调起 getOrderStatus 接口，获取最新物流数据";
                        } else if (
                          descLower.includes("refund") ||
                          descLower.includes("processrefund")
                        ) {
                          zhDesc =
                            "成功调起 processRefund 接口，执行快速退款并修改物理表";
                        } else if (
                          descLower.includes("screenshot") ||
                          descLower.includes("takescreenshot")
                        ) {
                          zhDesc =
                            "成功调起 takeScreenshot 接口，生成目标看板快照";
                        } else if (
                          descLower.includes("inform") ||
                          descLower.includes("communicate") ||
                          descLower.includes("tell")
                        ) {
                          zhDesc = "通过大模型提炼汇总信息反馈给用户";
                        }
                        return {
                          ...sub,
                          description: zhDesc,
                          result: sub.result,
                        };
                      }),
                    }
                  : undefined,
                jobId,
              };
            }
            return next;
          });

          fetchThreads();

          setActivePlan(null);
          setCurrentStepText("");
          setIsSubmitting(false);
        });

        eventSource.addEventListener("error", (event: Event) => {
          console.error("SSE Error:", event);
          eventSource.close();
          setIsSubmitting(false);
          setCurrentStepText("");
          setActivePlan(null);
        });
      } catch (err) {
        console.error("Failed to initialize stream", err);
        setIsSubmitting(false);
      }
    },
    [fetchThreads],
  );

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isSubmitting || !activeThreadId || !currentUser)
      return;

    const userQuery = input;
    setInput("");
    setIsSubmitting(true);
    setTokensConsumed(0);

    const userMessage: Message = { role: "user", content: userQuery };
    const loaderMessage: Message = {
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
        }),
      });

      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.error || "创建执行链路失败");
      }

      if (data.isHumanActive) {
        setMessages((prev) => prev.filter((m) => m.jobId !== "pending-job"));
        setIsSubmitting(false);
        await loadHistory(activeThreadId);
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
