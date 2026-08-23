import * as fs from 'node:fs';
import * as path from 'node:path';
import { getDrizzle, ragDocuments } from 'db';
import { and, eq } from 'drizzle-orm';
import { getEmbeddingModel } from '../llm/callLLMWithRetry';
import { MarkdownChunker } from './chunker';
import { generateContextualSummary } from './contextGenerator';
import { type RAGCategory, classifyChunkCategory, parseFrontmatter } from './ingestTxtFiles';

export interface UpsertChunkOptions {
  businessId: string;
  sourceUrl: string;
  docTitle: string;
  headerPath: string;
  chunkText: string;
  category?: RAGCategory;
}

/**
 * 物理单切片更新/覆盖 (Upsert Single Chunk)
 * 若同商户、同文件且同章节路径已存在，则覆盖更新文本与向量，否则插入新记录
 */
export async function upsertDocumentChunk(opts: UpsertChunkOptions): Promise<string> {
  const drizzle = getDrizzle();
  if (!drizzle) throw new Error('Database connection not ready');

  const embeddingModel = getEmbeddingModel();
  const category = await classifyChunkCategory(opts.headerPath, opts.chunkText, opts.category);
  const summary = await generateContextualSummary(opts.docTitle, opts.headerPath, opts.chunkText, opts.businessId);

  const combinedText = `[Context] ${summary}\n\n[Content] ${opts.chunkText}`;
  const embedding = await embeddingModel.embedQuery(combinedText);
  const serializedEmbedding = JSON.stringify(embedding);

  // 检查是否存在现有同源或同内容切片（防止产生重复数据）
  const existing = await drizzle
    .select({ id: ragDocuments.id })
    .from(ragDocuments)
    .where(and(eq(ragDocuments.businessId, opts.businessId), eq(ragDocuments.chunkText, opts.chunkText)))
    .limit(1);

  const matched = existing[0];

  if (matched) {
    await drizzle
      .update(ragDocuments)
      .set({
        chunkText: opts.chunkText,
        contextualSummary: summary,
        embedding: serializedEmbedding,
        metadata: {
          category,
          docTitle: opts.docTitle,
          headerPath: opts.headerPath,
          sourceFile: opts.sourceUrl,
          updatedAt: new Date().toISOString(),
        },
      })
      .where(eq(ragDocuments.id, matched.id));
    return matched.id;
  }

  const [inserted] = await drizzle
    .insert(ragDocuments)
    .values({
      businessId: opts.businessId,
      sourceUrl: opts.sourceUrl,
      chunkText: opts.chunkText,
      contextualSummary: summary,
      embedding: serializedEmbedding,
      metadata: {
        category,
        docTitle: opts.docTitle,
        headerPath: opts.headerPath,
        sourceFile: opts.sourceUrl,
        updatedAt: new Date().toISOString(),
      },
    })
    .returning({ id: ragDocuments.id });

  return inserted.id;
}

/**
 * 物理删除源文件对应的所有历史 RAG 切片 (Delete Chunks By Source)
 */
export async function deleteChunksBySource(businessId: string, sourceUrl: string): Promise<number> {
  const drizzle = getDrizzle();
  if (!drizzle) return 0;

  const result = await drizzle
    .delete(ragDocuments)
    .where(and(eq(ragDocuments.businessId, businessId), eq(ragDocuments.sourceUrl, sourceUrl)));

  return result.rowCount ?? 0;
}

/**
 * 热替换整个知识库文件 (Replace Full Knowledge File)
 * 场景：商家修改了《退换货政策.md》，清空旧切片并重新进行切片、Contextual Summary 与 Embedding 物理落盘
 */
export async function replaceKnowledgeFile(filePath: string, overrideBusinessId?: string): Promise<number> {
  const drizzle = getDrizzle();
  if (!drizzle) return 0;

  const fileName = path.basename(filePath);
  const rawContent = fs.readFileSync(filePath, 'utf-8');
  const { frontmatter, body } = parseFrontmatter(rawContent);

  let businessId = overrideBusinessId || frontmatter.businessId || 'ecommerce';
  if (!frontmatter.businessId && !overrideBusinessId) {
    const lower = fileName.toLowerCase();
    if (lower.includes('nike')) businessId = 'nike';
    else if (lower.includes('adidas')) businessId = 'adidas';
  }

  // 1. 物理安全清理旧切片数据
  await deleteChunksBySource(businessId, fileName);

  // 2. 重新切割并增量写入新切片
  let docTitle = frontmatter.title || '';
  if (!docTitle) {
    const firstLine = body.split('\n')[0] || '';
    docTitle = firstLine.replace(/^#+\s*/, '').trim() || fileName;
  }

  const explicitCategory = frontmatter.category as RAGCategory | undefined;
  const chunks = MarkdownChunker.splitMarkdown(body, {
    maxChunkSize: 500,
    category: explicitCategory,
  });

  let insertedCount = 0;
  for (const chunk of chunks) {
    await upsertDocumentChunk({
      businessId,
      sourceUrl: fileName,
      docTitle,
      headerPath: chunk.headerPath,
      chunkText: chunk.chunkText,
      category: explicitCategory,
    });
    insertedCount++;
  }

  console.log(`[ReplaceRAG] 🔄 成功全量替换知识文件 ${fileName} (商户: ${businessId}, 新切片数: ${insertedCount})`);
  return insertedCount;
}
