import { logger } from 'observability';
import { getLLM } from '../../llm/callLLMWithRetry';
import type { AgentStateAnnotation } from '../state';

export async function finishNode(state: typeof AgentStateAnnotation.State) {
  logger.info({ threadId: state.threadId }, 'finishNode formulating final response');

  const plan = state.taskPlan || { subtasks: [] };
  const input = state.input;
  const llm = getLLM(state.jobId);

  // 📦 SaaS Contextual RAG: 将多租户隔离检索出的企业知识库和标准业务政策（SOP）注入 Prompt，使回复回答完全匹配对应商户规则，彻底杜绝多租户政策幻觉混淆
  let ragContext = '';
  if (state.ragDocuments && state.ragDocuments.length > 0) {
    const formattedDocs = state.ragDocuments
      .map((doc: any, idx: number) => {
        return `[Store Policy Rule ${idx + 1}] (Context Summary: ${doc.contextualSummary}): "${doc.chunkText}"`;
      })
      .join('\n');
    ragContext = `\n\n[RELEVANT STORE POLICIES & KNOWLEDGE BASE]:\n${formattedDocs}\nIf relevant, explain these policies politely to the customer in Chinese to justify why certain actions (like returns or shipping constraints) can or cannot be taken, and strictly ground your explanation on these rules.`;
  }

  const systemPrompt =
    state.businessConfig?.systemPrompt ||
    'You are an advanced, professional AI Customer Support Agent specialized in E-Commerce. Help users resolve order, shipping, and refund queries.';

  // 🚀 会话上下文记忆：将历史消息拼装注入，大模型在总结生成最终答复时，能够完美串联多轮对话上下文脉络
  let historyContext = '';
  if (state.shortMemory && state.shortMemory.length > 0) {
    const formattedHistory = state.shortMemory
      .map((m: any) => {
        if (!m) return '';
        const role = m.role === 'user' ? 'Customer' : 'Agent';
        const content = m.content;
        if (content === undefined || content === null || String(content).trim() === '' || String(content) === 'undefined' || String(content) === 'null') {
          return '';
        }
        return `${role}: "${String(content).trim()}"`;
      })
      .filter((line: string) => line !== '')
      .join('\n');
    historyContext = `\n\n[CONVERSATION HISTORY (PAST TURNS)]:\n${formattedHistory}`;
  }

  const prompt = `System Instruction Context: "${systemPrompt}"
Formulate a clean, professional, and helpful customer support message in Chinese.
Customer Question: "${input}"
The plan execution details (the ultimate truth from physical database) are: ${JSON.stringify(plan.subtasks || [])}${ragContext}${historyContext}Locally discussed details might also reside in the conversation history above.

CRITICAL RULES (最高行为准则 - 严禁幻觉):
1. If the customer is asking about what was just discussed, what actions were just performed in previous turns, or meta-questions about the conversation history (e.g., "刚退款的是哪笔订单?", "我们刚刚查了什么?"), you MUST answer based on the [CONVERSATION HISTORY (PAST TURNS)] above.
2. Otherwise, for any new queries regarding order status or refunds that executed tools in the current turn, you must answer 100% based on the REAL tools results in the current subtasks list.
3. If any tool returned an error (e.g., "Order not found in the physical database" or "Failed to process"), you MUST honestly inform the customer in Chinese that the order does not exist in our database or the tool failed. DO NOT hallucinate, DO NOT fabricate any shipped status, and DO NOT guess any tracking numbers or dates!
4. If the tool executed successfully and returned the order details (status, carrier, etc.), you summarize them accurately.
5. Keep the output professional, polite, and fully in Chinese.`;

  try {
    const response = await llm.invoke(prompt);
    const content = typeof response === 'string' ? response : (response as any).content || '';
    logger.info({ threadId: state.threadId }, 'finishNode response formulated successfully');
    return { output: content.trim() };
  } catch (err: any) {
    logger.error({ threadId: state.threadId, err }, 'finishNode failed, using fallback summary');
    return {
      output: `Your request has been processed. Status details: ${JSON.stringify((plan.subtasks || []).map((s: any) => s.result))}`,
    };
  }
}
