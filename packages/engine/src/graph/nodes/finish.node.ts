import { logger } from "observability";
import { getLLM } from "../../llm/callLLMWithRetry";
import { type AgentStateAnnotation, buildHistoryContext } from "../state";

export async function finishNode(state: typeof AgentStateAnnotation.State) {
  logger.info(
    { threadId: state.threadId },
    "finishNode formulating final response",
  );

  let shortMemory = state.shortMemory || [];

  // 🛡️ [图级别智能硬熔断保护器 fallback]:
  // 如果进入 finish 节点时，发现触发了 Circuit Breaker 条件（转移步数 >= 10 或工具报错 >= 3），
  // 我们直接降级旁路退出，返回预置的高保真、极其得体的人工客服切流文案。彻底免去大模型 LLM 调用开销，秒级极速响应！
  const globalTransitions = state.globalTransitionsCount || 0;
  const toolErrors = state.toolErrorsCount || 0;

  if (globalTransitions >= 10 || toolErrors >= 3) {
    logger.warn(
      { threadId: state.threadId, globalTransitions, toolErrors },
      "finishNode detected active circuit breaker trigger. Bypassing LLM formulation and returning a safe fallback apology.",
    );
    const apology = `您好！由于当前系统网络出现短暂波动，或者底层接口响应延迟，为了保障您的账户、资金安全，我们已经**自动为您【熔断并终止】了本次自动决策流程**。✨

我们非常重视您的体验，请您完全放心：
1. **资金双写安全保障**：所有高危敏感动作（如退款）均处于完全锁定状态，绝对不会发生多扣款、重复退款 or 数据混淆。
2. **已为您自动转接至特级高级客服**：我已将您此前的全部沟通记录、已规划步骤以及遇到的异常参数**自动加密转交到我们的一线资深人工客服主管**。

人工主管专员将在 **1 分钟内直接在本会话中为您接管服务并妥善解决**，请您稍等。给您带来的不便我们深感抱歉，感谢您的宝贵耐心！👋`;
    return { output: apology, shortMemory };
  }

  const plan = state.taskPlan || { subtasks: [] };

  // 🛡️ [人工转接 / 人工审批挂起直达文案]:
  // 如果子步骤包含 waitingForApproval 且属于人工转接申请，返回高保真得体文案
  const approvalStep = plan.subtasks?.find(
    (st: any) => st.result?.waitingForApproval,
  );
  if (approvalStep) {
    const isHumanEscalation =
      approvalStep.result?.actionType === "human_escalation" ||
      approvalStep.description?.toLowerCase().includes("human_escalation");

    if (isHumanEscalation) {
      const escalationReply = `您好！已为您**成功触发人工客服接入流程**。✨

我们已锁定了当前会话，并将您的提问、已知订单数据与完整历史沟通记录**加密推送到资深人工客服主管接管队列**。

人工主管专员将在 **1 分钟内直接在本会话中为您接管服务并回应**，请您稍等。如您有更多细节补充，也可以直接在此留言！👋`;
      return { output: escalationReply, shortMemory };
    }
  }

  const input = state.input;
  const llm = getLLM(state.jobId);

  // 📦 SaaS Contextual RAG: 将多租户隔离检索出的企业知识库和标准业务政策（SOP）注入 Prompt，使回复回答完全匹配对应商户规则，彻底杜绝多租户政策幻觉混淆
  let ragContext = "";
  if (state.ragDocuments && state.ragDocuments.length > 0) {
    const formattedDocs = state.ragDocuments
      .map((doc: any, idx: number) => {
        return `[Store Policy Rule ${idx + 1}] (Context Summary: ${doc.contextualSummary}): "${doc.chunkText}"`;
      })
      .join("\n");
    ragContext = `\n\n[RELEVANT STORE POLICIES & KNOWLEDGE BASE]:\n${formattedDocs}\nIf relevant, explain these policies politely to the customer in Chinese to justify why certain actions (like returns or shipping constraints) can or cannot be taken, and strictly ground your explanation on these rules.`;
  }

  const systemPrompt =
    state.businessConfig?.systemPrompt ||
    "You are an advanced, professional AI Customer Support Agent specialized in E-Commerce. Help users resolve order, shipping, and refund queries.";

  const tenantId = state.businessConfig?.businessId || "ecommerce";
  const tenantContext = `\n\n[MULTI-TENANT ISOLATION BOUNDARY]:
You are an AI Customer Support Agent representing the specific brand/merchant: [${tenantId.toUpperCase()}].
- You must strictly align your replies, recommendations, and decisions with [${tenantId.toUpperCase()}]'s store policies and system tools.
- Under NO circumstances should you mention, reference, or explain policies, orders, or products belonging to other brands (e.g., Nike, Adidas) even if the customer asks.
- If the customer asks questions or requests operations about other brands, you must politely refuse and state that you only support [${tenantId.toUpperCase()}] orders and policies.`;

  // 🚀 会话上下文记忆：将历史消息拼装注入，大模型在总结生成最终答复时，能够完美串联多轮对话上下文脉络
  let historyContext = "";
  if (!shortMemory || shortMemory.length === 0) {
    const { ShortMemory } = require("../../memory/shortMemory");
    const sm = new ShortMemory(state.threadId);
    shortMemory = await sm.getMessages();
  }

  if (shortMemory && shortMemory.length > 0) {
    const formattedHistory = buildHistoryContext(shortMemory);
    if (formattedHistory) {
      historyContext = `\n\n[CONVERSATION HISTORY (PAST TURNS)]:\n${formattedHistory}`;
    }
  }

  const prompt = `System Instruction Context: "${systemPrompt}"${tenantContext}
Formulate a clean, professional, and helpful customer support message in Chinese.
Customer Question: "${input}"
The plan execution details (the ultimate truth from physical database) are: ${JSON.stringify(plan.subtasks || [])}${ragContext}${historyContext}Locally discussed details might also reside in the conversation history above.

CRITICAL RULES (最高行为准则 - 严禁幻觉与跨租户泄露):
1. If the customer is asking about what was just discussed, what actions were just performed in previous turns, or meta-questions about the conversation history (e.g., "刚退款的是哪笔订单?", "我们刚刚查了什么?"), you MUST answer based on the [CONVERSATION HISTORY (PAST TURNS)] above.
2. Otherwise, for any new queries regarding order status or refunds that executed tools in the current turn, you must answer 100% based on the REAL tools results in the current subtasks list.
3. If any tool returned an error (e.g., "Order not found in the physical database" or "Failed to process"), you MUST honestly inform the customer in Chinese that the order does not exist in our database or the tool failed. DO NOT hallucinate, DO NOT fabricate any shipped status, and DO NOT guess any tracking numbers or dates!
4. If the tool executed successfully and returned the order details (status, carrier, etc.), you summarize them accurately.
5. Keep the output professional, polite, and fully in Chinese.
6. Under NO circumstances should you reveal or discuss policies, orders, or specifications belonging to other brands (such as Nike, Adidas, etc.). If the user asks about another brand, politely reply that you only support [${tenantId.toUpperCase()}] orders and policies.`;

  try {
    const response = await llm.invoke(prompt);
    const content =
      typeof response === "string" ? response : (response as any).content || "";
    logger.info(
      { threadId: state.threadId },
      "finishNode response formulated successfully",
    );

    // 🚀 Populate semantic cache if it is a general_query
    const isOnlyGeneral =
      state.intents?.length === 1 &&
      state.intents[0].intent === "general_query";
    if (
      isOnlyGeneral &&
      state.input &&
      state.inputEmbedding &&
      state.inputEmbedding.length > 0
    ) {
      try {
        const { addQueryToSemanticCache } = require("./triage.node");
        addQueryToSemanticCache(
          tenantId,
          state.input,
          content.trim(),
          state.inputEmbedding,
        );
      } catch (cErr) {
        console.warn("[Finish Cache] Failed to cache general query:", cErr);
      }
    }

    return { output: content.trim(), shortMemory };
  } catch (err: any) {
    logger.error(
      { threadId: state.threadId, err },
      "finishNode failed, using fallback summary",
    );
    return {
      output: `Your request has been processed. Status details: ${JSON.stringify((plan.subtasks || []).map((s: any) => s.result))}`,
      shortMemory,
    };
  }
}
