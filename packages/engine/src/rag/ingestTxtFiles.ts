import * as fs from 'node:fs';
import * as path from 'node:path';
import { getDrizzle, ragDocuments } from 'db';
import { and, eq } from 'drizzle-orm';
import { getEmbeddingModel, getLLM } from '../llm/callLLMWithRetry';
import { MarkdownChunker } from './chunker';
import { generateContextualSummary } from './contextGenerator';

export type RAGCategory =
  | 'store_info'
  | 'product_knowledge'
  | 'operation_guide'
  | 'refund_policy'
  | 'size_chart'
  | 'general';

export interface IngestResult {
  filePath: string;
  businessId: string;
  chunksIngested: number;
}

/**
 * 提取文章开头的 YAML Frontmatter 元数据
 */
export function parseFrontmatter(rawContent: string): {
  frontmatter: Record<string, string>;
  body: string;
} {
  const match = rawContent.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!match) {
    return { frontmatter: {}, body: rawContent };
  }

  const yamlLines = match[1].split('\n');
  const frontmatter: Record<string, string> = {};
  for (const line of yamlLines) {
    const parts = line.split(':');
    if (parts.length >= 2) {
      const key = parts[0].trim();
      const val = parts
        .slice(1)
        .join(':')
        .trim()
        .replace(/^["']|["']$/g, '');
      frontmatter[key] = val;
    }
  }

  return { frontmatter, body: match[2].trim() };
}

/**
 * 使用 LLM 零样本对文本切片进行智能精细分类
 */
export async function classifyChunkCategory(
  headerPath: string,
  chunkText: string,
  explicitCategory?: string,
): Promise<RAGCategory> {
  const validCategories: RAGCategory[] = [
    'store_info',
    'product_knowledge',
    'operation_guide',
    'refund_policy',
    'size_chart',
    'general',
  ];

  if (explicitCategory && validCategories.includes(explicitCategory as RAGCategory)) {
    return explicitCategory as RAGCategory;
  }

  if (process.env.NODE_ENV === 'test' || process.env.BUN_ENV === 'test') {
    return (explicitCategory as RAGCategory) || 'general';
  }

  try {
    const llm = getLLM();
    const prompt = `You are an AI document classifier for an e-commerce customer support RAG knowledge base.
Classify the following chunk into EXACTLY ONE of these categories:
- "store_info": Store hours, physical store addresses, phone numbers, location guides
- "product_knowledge": Product materials, washing/cleaning/care instructions, shoe sizing, outfit matching
- "operation_guide": How-to SOP steps for invoice application, shipping address modifications
- "refund_policy": Returns, exchange timeframes, shipping fee coverage
- "size_chart": Size charts, shoe/apparel dimension comparisons
- "general": Uncategorized content

Header Path: "${headerPath}"
Chunk Content: "${chunkText}"

Return ONLY the category string (e.g. store_info). Do NOT include extra formatting or quotes.`;

    const res = await llm.invoke(prompt);
    let cat = res && typeof res.content === 'string' ? res.content.trim().toLowerCase() : '';
    cat = cat.replace(/[^a-z_]/g, '');

    if (validCategories.includes(cat as RAGCategory)) {
      return cat as RAGCategory;
    }
  } catch (err) {
    console.warn('[CategoryClassifier] LLM classification failed, falling back to general:', err);
  }

  return 'general';
}

/**
 * 自动化读取指定 TXT / Markdown 知识库目录并智能向量化切片入库
 */
export async function ingestTxtDirectory(knowledgeDir: string): Promise<IngestResult[]> {
  const drizzle = getDrizzle();
  if (!drizzle) {
    console.warn('[IngestTxt] PostgreSQL 连接不可用，跳过物理入库。');
    return [];
  }

  if (!fs.existsSync(knowledgeDir)) {
    console.warn(`[IngestTxt] 目录 ${knowledgeDir} 不存在。`);
    return [];
  }

  const files = fs.readdirSync(knowledgeDir).filter((f) => f.endsWith('.txt') || f.endsWith('.md'));
  const results: IngestResult[] = [];
  const embeddingModel = getEmbeddingModel();

  for (const file of files) {
    const filePath = path.join(knowledgeDir, file);
    const rawContent = fs.readFileSync(filePath, 'utf-8');

    // 1. 解析 YAML Frontmatter 元数据
    const { frontmatter, body } = parseFrontmatter(rawContent);

    // 优先读取 Frontmatter 中的 businessId，无则根据文件名或默认补全
    let businessId = frontmatter.businessId || 'ecommerce';
    if (!frontmatter.businessId) {
      const lowerFile = file.toLowerCase();
      if (lowerFile.includes('nike')) businessId = 'nike';
      else if (lowerFile.includes('adidas')) businessId = 'adidas';
    }

    // 优先读取 Frontmatter 中的 title，无则提取 H1 标题
    let docTitle = frontmatter.title || '';
    if (!docTitle) {
      const firstLine = body.split('\n')[0] || '';
      docTitle = firstLine.replace(/^#+\s*/, '').trim() || file;
    }

    const explicitCategory = frontmatter.category;

    // 2. 结构化 Markdown 切片
    const chunks = MarkdownChunker.splitMarkdown(body, {
      maxChunkSize: 500,
      category: explicitCategory,
    });

    // 3. 并行并发生成分类、Contextual Summary 与算力 Embeddings
    const chunkPromises = chunks.map(async (chunk) => {
      const category = await classifyChunkCategory(chunk.headerPath, chunk.chunkText, explicitCategory);

      const summary = await generateContextualSummary(docTitle, chunk.headerPath, chunk.chunkText, businessId);

      const combinedText = `[Context] ${summary}\n\n[Content] ${chunk.chunkText}`;
      const embedding = await embeddingModel.embedQuery(combinedText);
      const serializedEmbedding = JSON.stringify(embedding);

      return {
        businessId,
        sourceUrl: file,
        chunkText: chunk.chunkText,
        contextualSummary: summary,
        embedding: serializedEmbedding,
        metadata: {
          category,
          docTitle,
          headerPath: chunk.headerPath,
          sourceFile: file,
          ingestedAt: new Date().toISOString(),
        },
      };
    });

    const recordsToInsert = await Promise.all(chunkPromises);

    // 幂等入库：先清理同商户同文件的历史切片，防止重复累加
    await drizzle
      .delete(ragDocuments)
      .where(and(eq(ragDocuments.businessId, businessId), eq(ragDocuments.sourceUrl, file)));

    for (const record of recordsToInsert) {
      // 检查是否已有相同租户且相同文本的切片（例如早期无 sourceUrl 的种子数据），有则更新无则新增
      const existing = await drizzle
        .select({ id: ragDocuments.id })
        .from(ragDocuments)
        .where(and(eq(ragDocuments.businessId, record.businessId), eq(ragDocuments.chunkText, record.chunkText)))
        .limit(1);

      if (existing.length > 0) {
        await drizzle.update(ragDocuments).set(record).where(eq(ragDocuments.id, existing[0].id));
      } else {
        await drizzle.insert(ragDocuments).values(record);
      }
    }

    const count = recordsToInsert.length;

    results.push({
      filePath,
      businessId,
      chunksIngested: count,
    });

    console.log(`[IngestTxt] ✅ 成功入库文件 ${file} (商户: ${businessId}, 切片数: ${count})`);
  }

  return results;
}
