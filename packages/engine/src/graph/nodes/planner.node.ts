import { logger } from "observability";
import { getLLM } from "../../llm/callLLMWithRetry";
import { agentEventEmitter } from "../eventEmitter";
import { type AgentStateAnnotation, buildHistoryContext } from "../state";

export async function plannerNode(state: typeof AgentStateAnnotation.State) {
  logger.info(
    { threadId: state.threadId },
    "plannerNode starting step planning",
  );

  const intents = state.intents;
  const input = state.input;

  // 🧠 极致性能加速与直达：
  // 如果在 Triage 阶段或前置拦截中已经确定是单纯的日常问询/打招呼（general_query），
  // 我们在 Planner 阶段直接对 subtasks 进行硬性旁路截断，规划一个最极简的 Null 步骤，使其瞬间穿透并跳转到 Finish 阶段！
  const isOnlyGeneralQuery =
    intents.length === 1 && intents[0].intent === "general_query";
  if (isOnlyGeneralQuery) {
    const directPlan = {
      goal: "Bypass planner loop and respond to general query directly",
      subtasks: [
        {
          id: "respond_general",
          description: "Present general query response to user",
          status: "pending" as const,
        },
      ],
      currentStepIndex: 0,
    };

    logger.info(
      { threadId: state.threadId },
      "Bypassing complex planning for pure general_query.",
    );

    if (state.jobId) {
      agentEventEmitter.emit(`${state.jobId}:status`, {
        status: "executing",
        node: "planner",
        message:
          "检测到日常问询或欢迎语诉求，系统已完美启用【极速直达旁路】，无需进入复杂的工具规划与自旋校验环...",
        plan: directPlan,
      });
    }

    return { taskPlan: directPlan, globalTransitionsCount: 1 };
  }

  if (state.jobId) {
    agentEventEmitter.emit(`${state.jobId}:status`, {
      status: "executing",
      node: "planner",
      message: "正在根据分类意图，由大模型动态生成高精准子步骤执行规划...",
    });
  }

  // 🛡️ Plan-Preservation Bypass Check (HOT-RESUME):
  // If we are resuming from a suspended taskPlan that was waiting for approval, and the administrator approved
  // or user cancelled (meaning NOT rejected), we bypass LLM planning and reuse the existing plan entirely to preserve state!
  const priorPlan = state.taskPlan;
  if (priorPlan && priorPlan.subtasks && priorPlan.subtasks.length > 0) {
    const currentStep = priorPlan.subtasks[priorPlan.currentStepIndex];
    if (
      currentStep &&
      (currentStep.result?.waitingForApproval ||
        currentStep.status === "pending")
    ) {
      const {
        pendingApprovals: dbPendingApprovals,
        getDrizzle,
      } = require("db");
      const { eq, desc } = require("drizzle-orm");
      const drizzle = getDrizzle();
      if (drizzle) {
        try {
          const approvalsList = await drizzle
            .select()
            .from(dbPendingApprovals)
            .where(eq(dbPendingApprovals.threadId, state.threadId))
            .orderBy(desc(dbPendingApprovals.createdAt))
            .limit(1);
          const latestApproval = approvalsList[0];
          if (
            latestApproval &&
            (latestApproval.status === "approved" ||
              latestApproval.status === "cancelled")
          ) {
            console.log(
              `[Planner Bypass] 🔄 Step is ${latestApproval.status}. Reusing the existing taskPlan.`,
            );
            if (state.jobId) {
              agentEventEmitter.emit(`${state.jobId}:status`, {
                status: "executing",
                node: "planner",
                message: `🔄 恢复计划：检测到历史执行工单已人工审核决议为 [${latestApproval.status === "approved" ? "核准" : "取消"}]，跳过大模型规划，100% 物理复用历史步骤并精确恢复执行流！`,
                plan: priorPlan,
              });
            }
            return { taskPlan: priorPlan, globalTransitionsCount: 1 };
          }
        } catch (dbErr) {
          console.warn(
            "[Planner Bypass] Failed to check approval status for bypass:",
            dbErr,
          );
        }
      }
    }
  }

  // 🧠 Cognitive State Backtracking: 检查是否有先前的被退款拒绝步骤，如果有，将管理员反馈作为关键上下文喂给 Planner 促其重新规划路径
  let rejectionContext = "";
  if (priorPlan?.subtasks) {
    // 🛡️ 如果检测到管理员最新的审批结果是 'rejected'，我们动态将当前步骤标记为 failed 并打上 rejectedByAdmin 标记，以便进行认知重规划
    let latestApproval: any = null;
    const { pendingApprovals: dbPendingApprovals, getDrizzle } = require("db");
    const { eq, desc } = require("drizzle-orm");
    const drizzle = getDrizzle();
    if (drizzle) {
      try {
        const approvalsList = await drizzle
          .select()
          .from(dbPendingApprovals)
          .where(eq(dbPendingApprovals.threadId, state.threadId))
          .orderBy(desc(dbPendingApprovals.createdAt))
          .limit(1);
        latestApproval = approvalsList[0];
      } catch (dbErr) {
        console.warn(
          "[Planner Rejection Check] Failed to check latest approval for backtracking:",
          dbErr,
        );
      }
    }

    if (latestApproval && latestApproval.status === "rejected") {
      const currentStepIndex = priorPlan.currentStepIndex;
      const step = priorPlan.subtasks[currentStepIndex];
      if (
        step &&
        (step.result?.waitingForApproval ||
          step.status === "pending" ||
          step.status === "executing")
      ) {
        step.status = "failed";
        step.result = {
          ...step.result,
          rejectedByAdmin: true,
          rejectionReason:
            latestApproval.actionPayload?.rejectionReason ||
            latestApproval.reason ||
            "No reason provided",
        };
        console.log(
          `[Planner Rejection] Dynamically marked step ${step.id} as failed/rejected based on DB approval record`,
        );
      }
    }

    const rejectedStep = priorPlan.subtasks.find(
      (st) => st.status === "failed" && st.result?.rejectedByAdmin,
    );
    if (rejectedStep) {
      rejectionContext = `\n\n[CRITICAL ADVISORY]: A previous step "${rejectedStep.description}" was REJECTED by the Administrator.
Rejection feedback/reason: "${rejectedStep.result?.rejectionReason || "No reason provided"}".
Please replan and output an alternative approach that respects this rejection. Do NOT suggest the same rejected action. If a smaller refund was suggested, adjust the amount. If the user request cannot be fulfilled, generate a step to explain the reason politely to the user.`;
    }
  }

  // 📦 SaaS Contextual RAG: 将多租户隔离检索出的企业知识库和标准业务政策（SOP）注入 Prompt，强制 Planner 遵守对应商户退还时效
  let ragContext = "";
  if (state.ragDocuments && state.ragDocuments.length > 0) {
    const formattedDocs = state.ragDocuments
      .map((doc: any, idx: number) => {
        return `[Store Policy Rule ${idx + 1}] (Context Summary: ${doc.contextualSummary}): "${doc.chunkText}"`;
      })
      .join("\n");
    ragContext = `\n\n[RELEVANT BUSINESS POLICIES & KNOWLEDGE BASE]:\n${formattedDocs}\nStrictly adhere to these store policies while making the plan. If a policy specifies return timelines, tag conditions, or shipping methods, make sure any proposed subtasks or user communication steps strictly follow these rules.`;
  }

  const systemPrompt =
    state.businessConfig?.systemPrompt ||
    "You are an advanced, professional AI Customer Support Agent specialized in E-Commerce. Help users resolve order, shipping, and refund queries.";

  // 🚀 会话上下文记忆：将历史消息拼装注入，大模型即可敏捷关联上一轮提问中提到的核心要素（如订单号 ORD-98712 等）
  let historyContext = "";
  let shortMemory = state.shortMemory;
  if (!shortMemory || shortMemory.length === 0) {
    const { ShortMemory } = require("../../memory/shortMemory");
    const sm = new ShortMemory(state.threadId);
    shortMemory = await sm.getMessages();
  }

  if (shortMemory && shortMemory.length > 0) {
    const formattedHistory = buildHistoryContext(shortMemory);
    if (formattedHistory) {
      historyContext = `\n\n[CONVERSATION HISTORY (PAST TURNS)]:\n${formattedHistory}\n\n[CRITICAL DIRECTIVE]: Carefully read the conversation history above. If the customer is requesting a refund or action in their current input, and they have already provided a specific order ID in previous turns (or you have already queried it successfully), you MUST extract and use that order ID to formulate your subtasks (e.g. processRefund with orderId: ORD-98712). DO NOT plan to ask the customer for the order ID again if it was already mentioned or established in the history!`;
    }
  }

  const llm = getLLM(state.jobId);
  const prompt = `System Instruction Context: "${systemPrompt}"
Based on the intents: ${JSON.stringify(intents)} and input: "${input}", generate a sequence of structured steps (a plan) to satisfy the request.${rejectionContext}${ragContext}${historyContext}

[CRITICAL MULTI-TURN MEMORY & RETRIEVAL DIRECTIVES]:
1. Carefully inspect the [CONVERSATION HISTORY (PAST TURNS)] above. If the customer has already mentioned a specific Order ID (e.g., "ORD-98712") in previous turns, or if an Order ID was successfully checked earlier, you MUST assume the customer's current request (for refund, status query, or returns) is regarding that EXACT Order ID!
2. If the customer asks "我还有其他订单吗" (Do I have other orders?), "查询我名下的订单" (Query orders under my name), or wants to list their order history, you MUST plan a step to call the "listUserOrders" tool to fetch their recent order list.
3. If an Order ID (like "ORD-98712") is present in the history, bypass any placeholder check steps, and directly plan a concrete step to execute the requested action. For example: "Call the processRefund tool with orderId 'ORD-98712' to initiate the return/refund in our systems."
4. If NO Order ID exists anywhere in the conversation history, and they are asking for an order operation (refund, tracking), you should plan a step to call "listUserOrders" first to dynamically find their recent orders, or ask the customer to provide their Order ID if listUserOrders is unavailable or returns nothing.

Return a JSON object with:
- "goal": overall goal description
- "subtasks": array of objects with keys "id" (unique string), "description" (what to do, e.g., call tool getOrderStatus, or ask user for confirmation).
Return ONLY the raw JSON object. Do not include markdown or backticks.`;

  try {
    const response = await llm.invoke(prompt);
    const content =
      typeof response === "string" ? response : (response as any).content || "";
    let plan: any;
    try {
      const cleanResponse = content
        .trim()
        .replace(/^```json\s*/, "")
        .replace(/```$/, "")
        .trim();
      plan = JSON.parse(cleanResponse);
    } catch {
      // Fallback
      plan = {
        goal: "Address customer request",
        subtasks: intents.map((it, idx) => ({
          id: `step_${idx}`,
          description: `Handle ${it.intent} process`,
          status: "pending",
        })),
        currentStepIndex: 0,
      };
    }

    const taskPlan = {
      goal: plan.goal || "Handle customer request",
      subtasks: (plan.subtasks || []).map((sub: any) => ({
        id: sub.id,
        description: sub.description,
        status: "pending",
      })),
      currentStepIndex: 0,
    };

    logger.info(
      { threadId: state.threadId, taskPlan },
      "plannerNode step planning completed",
    );

    if (state.jobId) {
      agentEventEmitter.emit(`${state.jobId}:status`, {
        status: "executing",
        node: "planner",
        message: `子步骤物理规划成功！目标：${taskPlan.goal}，拆解为 ${taskPlan.subtasks.length} 个子任务。`,
        plan: taskPlan,
      });
    }

    return { taskPlan, shortMemory, globalTransitionsCount: 1 };
  } catch (err: any) {
    logger.error(
      { threadId: state.threadId, err },
      "plannerNode failed, falling back to default single-step plan",
    );
    return {
      taskPlan: {
        goal: "Answer customer queries",
        subtasks: [
          {
            id: "step_fallback",
            description: "Address request in fallback mode",
            status: "pending",
          },
        ],
        currentStepIndex: 0,
      },
      globalTransitionsCount: 1,
    };
  }
}
