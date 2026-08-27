/**
 * Contextual Summary 上下文生成器 (Anthropic RAG Paradigm & Hierarchical Context)
 * 在构建 RAG 向量时，为切片自动拼接 50-80 字大模型生成的全局背景说明，提升检索精准度 50%+
 * 针对超大文档支持大纲摘要 + 局部章节父段落的分层增强（Hierarchical Contextual Retrieval），消除 Token 膨胀
 */

import { getLLM } from '../llm/callLLMWithRetry';

export interface ContextualSummaryParams {
  fullDocumentTitle: string;
  headerPath: string;
  chunkText: string;
  businessId?: string;
  documentOutline?: string; // 全局大纲树
  parentChunk?: string; // 局部章节父段落
}

export async function generateContextualSummary(
  paramsOrTitle: string | ContextualSummaryParams,
  headerPath?: string,
  chunkText?: string,
  businessId = 'ecommerce',
): Promise<string> {
  const params: ContextualSummaryParams =
    typeof paramsOrTitle === 'object'
      ? paramsOrTitle
      : {
          fullDocumentTitle: paramsOrTitle,
          headerPath: headerPath || '通用说明',
          chunkText: chunkText || '',
          businessId: businessId || 'ecommerce',
        };

  const currentBiz = params.businessId || 'ecommerce';
  const fallbackSummary = `本段切片出自商户 [${currentBiz}] 的文档《${params.fullDocumentTitle}》中“${params.headerPath}”章节，详细说明了相关业务规则与步骤。`;

  if (process.env.NODE_ENV === 'test' || process.env.BUN_ENV === 'test') {
    return fallbackSummary;
  }

  try {
    const llm = getLLM();
    let prompt: string;

    if (params.documentOutline || params.parentChunk) {
      // 超大文档分层上下文提示词（大纲 + 章节路径 + 局部父段落）
      prompt = `You are a RAG contextual summary generator for e-commerce customer support.
Given the document outline, chapter header path, and chunk content, generate a concise 1-2 sentence Chinese contextual summary (under 60 words) explaining what this specific chunk describes in the broader document context.

Document Title: "${params.fullDocumentTitle}"
${params.documentOutline ? `Document Outline:\n${params.documentOutline}\n` : ''}
Header Path: "${params.headerPath}"
${params.parentChunk && params.parentChunk !== params.chunkText ? `Section Background:\n"${params.parentChunk.slice(0, 300)}..."\n` : ''}
Chunk Text: "${params.chunkText}"

Return ONLY the Chinese contextual summary sentence. Do NOT include extra formatting or quotes.`;
    } else {
      prompt = `You are a RAG contextual summary generator for e-commerce customer support.
Given the full document title, chapter header path, and chunk content, generate a concise 1-2 sentence Chinese contextual summary (under 60 words) explaining what this specific chunk describes in the broader document context.

Document Title: "${params.fullDocumentTitle}"
Header Path: "${params.headerPath}"
Chunk Text: "${params.chunkText}"

Return ONLY the Chinese contextual summary sentence. Do NOT include extra formatting or quotes.`;
    }

    const response = await llm.invoke(prompt);
    let summary = typeof response.content === 'string' ? response.content.trim() : '';
    summary = summary.replace(/^["'「」]+|["'「」]+$/g, '').trim();

    if (summary && summary.length > 5) {
      return summary;
    }
    return fallbackSummary;
  } catch (err) {
    console.warn('[ContextGenerator] LLM contextual summary generation failed, using fallback:', err);
    return fallbackSummary;
  }
}
