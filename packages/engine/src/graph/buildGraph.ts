import { END, StateGraph } from "@langchain/langgraph";
import { logger } from "observability";
import { getEmbeddingModel } from "../llm/callLLMWithRetry";
import { EpisodicMemory, LongMemory, ShortMemory, TaskMemory } from "../memory";
import { agentEventEmitter } from "./eventEmitter";
import { executorNode } from "./nodes/executor.node";
import { finishNode } from "./nodes/finish.node";
import { mergeNode } from "./nodes/merge.node";
import { plannerNode } from "./nodes/planner.node";
import { triageNode } from "./nodes/triage.node";
import { validatorNode } from "./nodes/validator.node";
import { AgentStateAnnotation } from "./state";

export function buildAgentGraph() {
  const workflow = new StateGraph(AgentStateAnnotation)
    // Add nodes
    .addNode("triage", triageNode)
    .addNode("planner", plannerNode)
    .addNode("merge", mergeNode)
    .addNode("executor", executorNode)
    .addNode("validator", validatorNode)
    .addNode("finish", finishNode);

  // Setup workflow flow starting with triage
  workflow.addEdge("__start__", "triage");

  // Route after triage
  workflow.addConditionalEdges(
    "triage",
    (state) => {
      // 🧠 极致提速优化（Bypass Loop Logic）：
      // 如果没有检测到任何意图，或者识别出的唯一意图是纯日常咨询/打招呼（general_query），
      // 证明本次会话不需要物理数据库或截图工具链的编排。我们直接切入 Finish 终点，彻底省去 Planner -> Executor -> Validator 重置循环！
      if (state.intents.length === 0) {
        return "finish";
      }

      const isOnlyGeneralQuery =
        state.intents.length === 1 &&
        state.intents[0].intent === "general_query";
      if (isOnlyGeneralQuery) {
        logger.info(
          { threadId: state.threadId },
          "Detected pure general_query, bypassing planner loop to finishNode directly.",
        );
        return "finish";
      }

      return "planner";
    },
    {
      planner: "planner",
      finish: "finish",
    },
  );

  // After planner, merge/validate task structure
  workflow.addEdge("planner", "merge");
  workflow.addEdge("merge", "executor");
  workflow.addEdge("executor", "validator");

  // Condition routing after validator to continue executor loop, replan, or finish
  workflow.addConditionalEdges(
    "validator",
    (state) => {
      const plan = state.taskPlan;
      const nextIndex = plan.currentStepIndex;

      // 🛡️ [图级别智能硬熔断保护器 (Graph-Level Smart Circuit Breaker)]:
      // 1. 如果全局节点转移步数大于等于 10 (例如 Planner/Executor/Validator 陷入智商自旋)，
      // 2. 或累计工具运行错误、核验失败次数达到 3 次，立刻强制物理触发【降级熔断】，直接返回 'finish'
      const globalTransitions = state.globalTransitionsCount || 0;
      const toolErrors = state.toolErrorsCount || 0;

      if (globalTransitions >= 10 || toolErrors >= 3) {
        logger.warn(
          { threadId: state.threadId, globalTransitions, toolErrors },
          "🛑 [CIRCUIT BREAKER TRIGGERED] Runaway loop or tool errors limit exceeded! Fusing execution to prevent API credit burn!",
        );
        return "finish";
      }

      // 1. 如果有任何子任务在等待审批，我们立刻提前终止 Graph 并路由到 finish 节点让其挂起！
      const hasWaitingStep = plan.subtasks.some(
        (st) => st.result?.waitingForApproval,
      );
      if (hasWaitingStep) {
        logger.info(
          { threadId: state.threadId },
          "Detected pending approval, routing to finish early to safely suspend.",
        );
        return "finish";
      }

      // 2. 如果有任何子任务被管理员驳回（status === 'failed' 且 result 里面有 rejectedByAdmin: true），
      // 且我们还没有进行重规划（即当前处于刚刚拒绝的那一步），我们选择【回溯】路由到 planner 重新进行决策规划！
      const hasJustBeenRejected = plan.subtasks.some(
        (st) =>
          st.status === "failed" &&
          st.result?.rejectedByAdmin &&
          !st.result?.replanned,
      );
      if (hasJustBeenRejected) {
        logger.info(
          { threadId: state.threadId },
          "Detected administrator rejection, routing BACK to planner for cognitive re-planning!",
        );
        // 标记该拒绝步骤已被重规划受理，防止无限循环
        plan.subtasks = plan.subtasks.map((st) =>
          st.status === "failed" && st.result?.rejectedByAdmin
            ? { ...st, result: { ...st.result, replanned: true } }
            : st,
        );
        return "planner";
      }

      // 3. Loop circuit breaker / safety check to avoid infinite loops
      if (nextIndex >= plan.subtasks.length || nextIndex >= 10) {
        logger.info(
          { threadId: state.threadId },
          "Plan steps completed, routing to finish",
        );
        return "finish";
      }

      logger.info(
        { threadId: state.threadId, nextIndex },
        "Routing back to executor for next step",
      );
      return "executor";
    },
    {
      executor: "executor",
      planner: "planner",
      finish: "finish",
    },
  );

  workflow.addEdge("finish", END);

  return workflow;
}

// 快速判定是否为基础的问候语或打招呼，实现毫秒级快速匹配，免去高昂的大模型开销！
function isQuickGreeting(msg: string): boolean {
  const clean = msg
    .trim()
    .toLowerCase()
    .replace(/[，。！？,.!?\s]/g, "");
  const greetings = [
    "你好",
    "您好",
    "哈喽",
    "哈罗",
    "hello",
    "hi",
    "hey",
    "你是谁",
    "你是哪个",
    "你是AI吗",
    "你是机器人吗",
    "who are you",
    "how are you",
  ];
  return greetings.includes(clean);
}

// Integrated invoke wrapper incorporating the 4 memories
export async function runAgent(
  threadId: string,
  userId: string,
  inputMessage: string,
  jobId?: string,
) {
  // Initialize memories
  const shortMemory = new ShortMemory(threadId);
  const longMemory = new LongMemory(userId);
  const taskMemory = new TaskMemory(threadId);
  const episodicMemory = new EpisodicMemory(userId);

  // 1. 🚀 毫秒级极速直达旁路：如果用户输入纯问候语/打招呼，跳过所有 LLM、向量数据库 RAG 检索！
  // 零模型开销，10毫秒瞬间完美响应！
  if (isQuickGreeting(inputMessage)) {
    const greetingText = `您好！我是您的智能电商客服助理。✨

我能为您提供以下高效率的自动化业务操作：
1. **订单物流查询**：例如 *“帮我查一下 ORD-98712 的发货状态”*
2. **快捷退款办理**：例如 *“帮我申请退款”*
3. **网页看板快照**：例如 *“帮我截取系统首页进行界面圆角核验”*

请告诉我您需要处理的业务，我将真刀真枪为您调起系统底层工具为您搞定！`;

    console.log(
      "[Quick Greeting Bypass] Trigerred 10ms lightning bypass response!",
    );

    // 先确保物理会话在数据库中落盘（防止 messages 表中 thread_id 外键约束报错导致存储失败）
    try {
      const { db } = require("db");
      await db.createThread(threadId, userId);
    } catch (threadErr) {
      console.warn(
        "[DB] Failed to ensure thread exists for quick greeting:",
        threadErr,
      );
    }

    await shortMemory.addMessage("user", inputMessage);
    await shortMemory.addMessage("assistant", greetingText);

    const mockResult = {
      output: greetingText,
      taskPlan: {
        goal: "Bypass planner loop and respond to quick greeting directly",
        subtasks: [
          {
            id: "respond_greeting",
            description: "Lightning bypass welcome message",
            status: "completed" as const,
            result: { message: "Bypassed successfully" },
          },
        ],
        currentStepIndex: 1,
      },
    };

    if (jobId) {
      agentEventEmitter.emit(`${jobId}:status`, {
        status: "executing",
        node: "triage",
        message:
          "极速通道：已秒级识别您所发送的日常打招呼，为您载入高画质欢迎界面...",
        plan: mockResult.taskPlan,
      });
      // 延迟极微小时间给 SSE 握手
      setTimeout(() => {
        agentEventEmitter.emit(`${jobId}:result`, mockResult);
      }, 100);
    }

    return mockResult;
  }

  // 2. 🔍 性能与成本优化：如果是字数极少的非问候短文本（长度 <= 3），没有检索长期记忆和知识库 RAG 的业务必要，
  // 我们直接避开耗时的 Embedding 向量化与 RAG 检索调用（节省 1.5 秒以上首字响应延迟！）
  let longFacts: any[] = [];
  let episodicEvents: any[] = [];
  let ragDocs: any[] = [];

  // SaaS 多租户隔离及高级动态政策热载入引擎
  let businessId = "ecommerce";
  let dynamicConfig = {
    businessId: "ecommerce",
    systemPrompt:
      "You are an advanced, professional AI Customer Support Agent specialized in E-Commerce. Help users resolve order, shipping, and refund queries.",
    intents: {
      order_status: { description: "Track or check order delivery status." },
      refund: { description: "Process or request refunds." },
      general_query: { description: "General customer questions." },
    },
    tools: [
      "getOrderStatus",
      "processRefund",
      "takeScreenshot",
      "listUserOrders",
    ],
    executionMode: "plan-and-execute",
    confidenceThresholds: { high: 0.85, mid: 0.6 },
    refundAutoApprovalLimit: 100, // 默认超过 $100 退款触发审批
  };

  // 1. 根据 threadId 物理查询对应的商户 businessId，并从物理表加载对应的活跃 JSON 规则快照，实现 Hot-Reloadable SaaS 政策。
  try {
    const { getDrizzle, threads, businessConfigs, db } = require("db");
    const { eq, and } = require("drizzle-orm");
    const drizzle = getDrizzle();
    if (drizzle) {
      // 🛡️ 最底层的多租户外键一致性保障：强行确保物理 threads 行在 messages 写入前已真实落盘
      await db.createThread(threadId, userId);

      const threadRows = await drizzle
        .select()
        .from(threads)
        .where(eq(threads.id, threadId))
        .limit(1);
      if (threadRows[0]?.businessId) {
        businessId = threadRows[0].businessId;
      }

      // 从 Postgres 物理表查询当前商户活跃（is_active = true）的最新 JSON 配置
      const configRows = await drizzle
        .select()
        .from(businessConfigs)
        .where(
          and(
            eq(businessConfigs.businessId, businessId),
            eq(businessConfigs.isActive, true),
          ),
        )
        .limit(1);

      if (configRows[0]?.config) {
        dynamicConfig = {
          ...dynamicConfig,
          ...(configRows[0].config as any),
          businessId,
        };
        console.log(
          `[SaaS Config Engine] ⚡ 动态热加载成功！商户 [${businessId}] 的最新政策规则已载入，退款免签阈值: $${dynamicConfig.refundAutoApprovalLimit}`,
        );
      } else {
        // 自愈装配（Nike: $150, Adidas: $120, 主站: $100）
        let defaultLimit = 100;
        if (businessId === "nike") defaultLimit = 150;
        else if (businessId === "adidas") defaultLimit = 120;

        dynamicConfig = {
          ...dynamicConfig,
          businessId,
          refundAutoApprovalLimit: defaultLimit,
        };
        console.log(
          `[SaaS Config Engine] 📦 物理表未载入配置，启用商户 [${businessId}] 默认热装配规则，免签阈值: $${defaultLimit}`,
        );
      }
    }
  } catch (err) {
    console.warn(
      "[SaaS Config Engine] Failed to dynamically load business config:",
      err,
    );
  }

  let precomputedEmbedding: number[] | undefined;

  // 2. 只有在文本字数足够多时，才并发运行三路大模型 RAG 与向量检索
  if (inputMessage.trim().length > 3) {
    const { ContextualRAG } = require("../rag/contextualRag");
    const contextualRag = new ContextualRAG(businessId);

    // 🧠 性能优化（单次向量化注入 Single-Embedding Injection）：
    // 在最外层仅调用一次 Embedding API，将唯一生成的向量参数作为指针传给三路 RAG，
    // 物理减少 2 次冗余的云端模型 network HTTPS 请求，首字响应时效瞬间提速 500ms - 1000ms 以上！
    const embeddingModel = getEmbeddingModel();
    try {
      precomputedEmbedding = await embeddingModel.embedQuery(inputMessage);
    } catch (embedErr) {
      console.error(
        "[runAgent] Failed to precompute embedding for Single-Embedding Injection:",
        embedErr,
      );
    }

    // 🚀 三路高度并行化 RAG 检索（长期事实记忆、情境记忆、多租户 Contextual 知识库检索）
    const [factsRes, eventsRes, ragRes] = await Promise.allSettled([
      longMemory.searchRelevantFacts(inputMessage, precomputedEmbedding),
      episodicMemory.retrieveEvents(inputMessage, 3, precomputedEmbedding),
      contextualRag.searchRelevantDocs(inputMessage, 2, precomputedEmbedding),
    ]);

    longFacts = factsRes.status === "fulfilled" ? factsRes.value : [];
    episodicEvents = eventsRes.status === "fulfilled" ? eventsRes.value : [];
    ragDocs = ragRes.status === "fulfilled" ? ragRes.value : [];
  }

  // Record user query in short memory
  await shortMemory.addMessage("user", inputMessage);

  // 🚀 获取最新的短期会话历史，无缝传递给状态图总线
  const historyMsgs = await shortMemory.getMessages();
  console.log(
    `\n[buildGraph Debug] Thread ${threadId} loaded historyMsgs:`,
    JSON.stringify(historyMsgs, null, 2),
    "\n",
  );

  // Load saved task state (if any) to support stateless suspension & recovery
  let savedTaskPlan: any = undefined;
  const isResuming = inputMessage.startsWith("System:");
  if (isResuming) {
    try {
      const state = await taskMemory.getTaskState();
      if (state) {
        savedTaskPlan = state;
        console.log(
          `[buildGraph] 🔄 Resuming suspended flow, loaded saved taskPlan:`,
          JSON.stringify(savedTaskPlan),
        );
      }
    } catch (err) {
      console.warn(
        "[buildGraph] Failed to load saved task plan from taskMemory:",
        err,
      );
    }
  }

  // Build and execute compiled graph
  const graphApp = buildAgentGraph().compile();

  const initialState = {
    threadId,
    userId,
    jobId: jobId || `job_local_${Date.now()}`,
    input: inputMessage,
    inputEmbedding: precomputedEmbedding,
    longMemoryFacts: longFacts,
    episodicEvents: episodicEvents,
    ragDocuments: ragDocs,
    businessConfig: dynamicConfig,
    shortMemory: historyMsgs,
    taskPlan: savedTaskPlan,
    loopCount: 0,
  };

  logger.info(
    { threadId, userId, jobId: initialState.jobId },
    "Invoking Agent StateGraph execution",
  );

  if (jobId) {
    agentEventEmitter.emit(`${jobId}:status`, {
      status: "running",
      message: "Local LangGraph execution engine initialized",
    });
  }

  let runId: string | undefined;
  const config = {
    callbacks: [
      {
        handleChainStart: (chain: any, inputs: any, id: string) => {
          if (!runId) runId = id;
        },
        handleLLMStart: (llm: any, prompts: any, id: string) => {
          if (!runId) runId = id;
        },
        handleToolStart: (tool: any, input: any, id: string) => {
          if (!runId) runId = id;
        },
      },
    ],
  };

  const startTime = Date.now();
  const result = await graphApp.invoke(initialState, config);
  const elapsedLatency = Date.now() - startTime;

  // 🪙 SaaS Telemetry: 物理记录本次会话的算力消耗、换算成本与图决策深度
  try {
    const totalTokens = agentEventEmitter.getTokens(initialState.jobId);
    const costUsd = (totalTokens / 1000000) * 0.15; // 按照每百万 Token $0.15 换算
    const nodeTransitions = result.loopCount || 3;

    let resolutionStatus = "resolved_auto";
    let isSuccess = true;
    let feedbackComment = "All planned subtasks completed successfully.";

    const plan = result.taskPlan;
    if (plan?.subtasks) {
      const hasPending = plan.subtasks.some(
        (st: any) => st.result?.waitingForApproval,
      );
      const hasCancelled = plan.subtasks.some(
        (st: any) => st.result?.cancelledByUser,
      );
      const hasExpired = plan.subtasks.some(
        (st: any) => st.result?.expiredByTimeout,
      );
      const hasRejected = plan.subtasks.some(
        (st: any) => st.status === "failed" && st.result?.rejectedByAdmin,
      );
      const hasFailed = plan.subtasks.some((st: any) => st.status === "failed");

      if (hasPending) {
        resolutionStatus = "waiting_approval";
      } else if (hasCancelled) {
        resolutionStatus = "cancelled";
      } else if (hasExpired) {
        resolutionStatus = "expired";
      } else if (hasRejected) {
        resolutionStatus = "rejected";
      } else if (hasFailed) {
        resolutionStatus = "failed";
        isSuccess = false;
        feedbackComment =
          "Some planned subtasks failed validation or execution.";
      }
    }

    // Report semantic feedback to LangSmith if runId is available and API key is set
    if (runId && process.env.LANGCHAIN_API_KEY) {
      const endpoint =
        process.env.LANGCHAIN_ENDPOINT || "https://api.smith.langchain.com";
      const apiKey = process.env.LANGCHAIN_API_KEY;

      // Async background fire-and-forget reporting to avoid blocking main execution
      (async () => {
        try {
          // Report 'correctness' feedback key
          const resCorrectness = await fetch(`${endpoint}/feedback`, {
            method: "POST",
            headers: {
              "x-api-key": apiKey,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              run_id: runId,
              key: "correctness",
              score: isSuccess ? 1.0 : 0.0,
              value: isSuccess ? "success" : "failure",
              comment: feedbackComment,
            }),
          });

          // Report 'success' feedback key (for alternative dashboards views)
          const resSuccess = await fetch(`${endpoint}/feedback`, {
            method: "POST",
            headers: {
              "x-api-key": apiKey,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              run_id: runId,
              key: "success",
              score: isSuccess ? 1.0 : 0.0,
              value: isSuccess ? "success" : "failure",
              comment: feedbackComment,
            }),
          });

          if (resCorrectness.ok && resSuccess.ok) {
            console.log(
              `[LangSmith Telemetry] Successfully uploaded "correctness" and "success" feedback scores for run ${runId}`,
            );
          } else {
            console.warn(
              `[LangSmith Telemetry] Failed to upload some feedback for run ${runId}. Correctness status: ${resCorrectness.status}, Success status: ${resSuccess.status}`,
            );
          }
        } catch (telemetryErr) {
          console.warn(
            "[LangSmith Telemetry] Error uploading feedback to LangSmith:",
            telemetryErr,
          );
        }
      })();
    }

    const { getDrizzle, sessionMetrics } = require("db");
    const drizzle = getDrizzle();
    if (drizzle) {
      await drizzle.insert(sessionMetrics).values({
        businessId: dynamicConfig.businessId,
        threadId: threadId,
        totalTokens: totalTokens,
        calculatedCostUsd: costUsd,
        nodeTransitionsCount: nodeTransitions,
        resolutionStatus: resolutionStatus,
        avgLatencyMs: elapsedLatency,
      });
      console.log(
        `[SaaS Telemetry] 📊 成功持久化会话审计：商户 [${dynamicConfig.businessId}]，Token 消耗: ${totalTokens}，换算成本: $${costUsd.toFixed(6)}，解挂状态: ${resolutionStatus}`,
      );
    }
  } catch (metricsErr) {
    console.warn(
      "[SaaS Telemetry] Failed to persist session metrics in physical table:",
      metricsErr,
    );
  }

  // Store assistant response back into memories
  if (result.output) {
    await shortMemory.addMessage("assistant", result.output);
    await episodicMemory.addEvent(
      `Handled conversation thread: ${threadId}. Output summary: ${result.output.substring(0, 80)}`,
      5,
    );
    await longMemory.extractAndStoreFact(result.output, inputMessage);
  }

  // Persist structured task memory if plan exists
  if (result.taskPlan) {
    await taskMemory.saveTaskState(result.taskPlan);
  }

  if (jobId) {
    agentEventEmitter.emit(`${jobId}:result`, result);
  }

  return result;
}
