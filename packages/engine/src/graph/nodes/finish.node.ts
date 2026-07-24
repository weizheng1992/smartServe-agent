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

  const prompt = `Formulate a clean, professional, and helpful customer support message in Chinese.
Customer Question: "${input}"
The plan execution details (the ultimate truth from physical database) are: ${JSON.stringify(plan.subtasks || [])}${ragContext}

CRITICAL RULES (最高行为准则 - 严禁幻觉):
1. You must answer the customer 100% based on the REAL tools results above.
2. If any tool returned an error (e.g., "Order not found in the physical database" or "Failed to process"), you MUST honestly inform the customer in Chinese that the order does not exist in our database or the tool failed. DO NOT hallucinate, DO NOT fabricate any shipped status, and DO NOT guess any tracking numbers or dates!
3. If the tool executed successfully and returned the order details (status, carrier, etc.), you summarize them accurately.
4. Keep the output professional, polite, and fully in Chinese.`;

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
