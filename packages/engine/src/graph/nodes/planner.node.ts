import { logger } from 'observability';
import { getLLM } from '../../llm/callLLMWithRetry';
import { agentEventEmitter } from '../eventEmitter';
import { type AgentStateAnnotation, buildHistoryContext } from '../state';

export async function plannerNode(state: typeof AgentStateAnnotation.State) {
  logger.info({ threadId: state.threadId }, 'plannerNode starting step planning');

  const intents = state.intents;
  const input = state.input;

  // 🧠 极致性能加速与直达：
  // 如果在 Triage 阶段或前置拦截中已经确定是单纯的日常问询/打招呼（general_query），
  // 我们在 Planner 阶段直接对 subtasks 进行硬性旁路截断，规划一个最极简的 Null 步骤，使其瞬间穿透并跳转到 Finish 阶段！
  const isOnlyGeneralQuery = intents.length === 1 && intents[0].intent === 'general_query';
  if (isOnlyGeneralQuery) {
    const directPlan = {
      goal: 'Bypass planner loop and respond to general query directly',
      subtasks: [
        {
          id: 'respond_general',
          description: 'Present general query response to user',
          status: 'pending' as const,
        },
      ],
      currentStepIndex: 0,
    };

    logger.info({ threadId: state.threadId }, 'Bypassing complex planning for pure general_query.');

    if (state.jobId) {
      agentEventEmitter.emit(`${state.jobId}:status`, {
        status: 'executing',
        node: 'planner',
        message: '检测到日常问询或欢迎语诉求，系统已完美启用【极速直达旁路】，无需进入复杂的工具规划与自旋校验环...',
        plan: directPlan,
      });
    }

    return { taskPlan: directPlan };
  }

  if (state.jobId) {
    agentEventEmitter.emit(`${state.jobId}:status`, {
      status: 'executing',
      node: 'planner',
      message: '正在根据分类意图，由大模型动态生成高精准子步骤执行规划...',
    });
  }

  // 🧠 Cognitive State Backtracking: 检查是否有先前的被退款拒绝步骤，如果有，将管理员反馈作为关键上下文喂给 Planner 促其重新规划路径
  const priorPlan = state.taskPlan;
  let rejectionContext = '';
  if (priorPlan?.subtasks) {
    const rejectedStep = priorPlan.subtasks.find((st) => st.status === 'failed' && st.result?.rejectedByAdmin);
    if (rejectedStep) {
      rejectionContext = `\n\n[CRITICAL ADVISORY]: A previous step "${rejectedStep.description}" was REJECTED by the Administrator.
Rejection feedback/reason: "${rejectedStep.result?.rejectionReason || 'No reason provided'}".
Please replan and output an alternative approach that respects this rejection. Do NOT suggest the same rejected action. If a smaller refund was suggested, adjust the amount. If the user request cannot be fulfilled, generate a step to explain the reason politely to the user.`;
    }
  }

  // 📦 SaaS Contextual RAG: 将多租户隔离检索出的企业知识库和标准业务政策（SOP）注入 Prompt，强制 Planner 遵守对应商户退还时效
  let ragContext = '';
  if (state.ragDocuments && state.ragDocuments.length > 0) {
    const formattedDocs = state.ragDocuments
      .map((doc: any, idx: number) => {
        return `[Store Policy Rule ${idx + 1}] (Context Summary: ${doc.contextualSummary}): "${doc.chunkText}"`;
      })
      .join('\n');
    ragContext = `\n\n[RELEVANT BUSINESS POLICIES & KNOWLEDGE BASE]:\n${formattedDocs}\nStrictly adhere to these store policies while making the plan. If a policy specifies return timelines, tag conditions, or shipping methods, make sure any proposed subtasks or user communication steps strictly follow these rules.`;
  }

  const systemPrompt =
    state.businessConfig?.systemPrompt ||
    'You are an advanced, professional AI Customer Support Agent specialized in E-Commerce. Help users resolve order, shipping, and refund queries.';

  // 🚀 会话上下文记忆：将历史消息拼装注入，大模型即可敏捷关联上一轮提问中提到的核心要素（如订单号 ORD-98712 等）
  let historyContext = '';
  if (state.shortMemory && state.shortMemory.length > 0) {
    const formattedHistory = buildHistoryContext(state.shortMemory);
    if (formattedHistory) {
      historyContext = `\n\n[CONVERSATION HISTORY (PAST TURNS)]:\n${formattedHistory}\n\n[CRITICAL DIRECTIVE]: Carefully read the conversation history above. If the customer is requesting a refund or action in their current input, and they have already provided a specific order ID in previous turns (or you have already queried it successfully), you MUST extract and use that order ID to formulate your subtasks (e.g. processRefund with orderId: ORD-98712). DO NOT plan to ask the customer for the order ID again if it was already mentioned or established in the history!`;
    }
  }

  const llm = getLLM(state.jobId);
  const prompt = `System Instruction Context: "${systemPrompt}"
Based on the intents: ${JSON.stringify(intents)} and input: "${input}", generate a sequence of structured steps (a plan) to satisfy the request.${rejectionContext}${ragContext}${historyContext}
Return a JSON object with:
- "goal": overall goal description
- "subtasks": array of objects with keys "id" (unique string), "description" (what to do, e.g., call tool getOrderStatus, or ask user for confirmation).
Return ONLY the raw JSON object. Do not include markdown or backticks.`;

  try {
    const response = await llm.invoke(prompt);
    const content = typeof response === 'string' ? response : (response as any).content || '';
    let plan: any;
    try {
      const cleanResponse = content
        .trim()
        .replace(/^```json\s*/, '')
        .replace(/```$/, '')
        .trim();
      plan = JSON.parse(cleanResponse);
    } catch {
      // Fallback
      plan = {
        goal: 'Address customer request',
        subtasks: intents.map((it, idx) => ({
          id: `step_${idx}`,
          description: `Handle ${it.intent} process`,
          status: 'pending',
        })),
        currentStepIndex: 0,
      };
    }

    const taskPlan = {
      goal: plan.goal || 'Handle customer request',
      subtasks: (plan.subtasks || []).map((sub: any) => ({
        id: sub.id,
        description: sub.description,
        status: 'pending',
      })),
      currentStepIndex: 0,
    };

    logger.info({ threadId: state.threadId, taskPlan }, 'plannerNode step planning completed');

    if (state.jobId) {
      agentEventEmitter.emit(`${state.jobId}:status`, {
        status: 'executing',
        node: 'planner',
        message: `子步骤物理规划成功！目标：${taskPlan.goal}，拆解为 ${taskPlan.subtasks.length} 个子任务。`,
        plan: taskPlan,
      });
    }

    return { taskPlan };
  } catch (err: any) {
    logger.error({ threadId: state.threadId, err }, 'plannerNode failed, falling back to default single-step plan');
    return {
      taskPlan: {
        goal: 'Answer customer queries',
        subtasks: [{ id: 'step_fallback', description: 'Address request in fallback mode', status: 'pending' }],
        currentStepIndex: 0,
      },
    };
  }
}
