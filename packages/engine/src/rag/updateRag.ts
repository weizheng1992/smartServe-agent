import * as fs from "node:fs";
import * as path from "node:path";
import { getDrizzle, ragDocuments } from "db";
import { and, eq, inArray } from "drizzle-orm";
import { getEmbeddingModel } from "../llm/callLLMWithRetry";
import { MarkdownChunker } from "./chunker";
import { generateContextualSummary } from "./contextGenerator";
import {
  type RAGCategory,
  classifyChunkCategory,
  parseFrontmatter,
} from "./ingestTxtFiles";

export interface UpsertChunkOptions {
  businessId: string;
  sourceUrl: string;
  docTitle: string;
  headerPath: string;
  chunkText: string;
  category?: RAGCategory;
  documentOutline?: string;
  parentChunk?: string;
}

export interface SyncFileResult {
  filePath: string;
  businessId: string;
  totalChunks: number;
  inserted: number;
  updated: number;
  unchanged: number;
  deleted: number;
}

/**
 * 限制最大并发执行数的异步映射器 (Concurrency Controller)
 * 防止大文档生成数十上百个切片时打爆 LLM / 向量接口的 Rate Limit
 */
export async function mapConcurrent<T, R>(
  items: T[],
  concurrency: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let currentIndex = 0;

  const workers = Array.from(
    { length: Math.min(concurrency, items.length) },
    async () => {
      while (currentIndex < items.length) {
        const idx = currentIndex++;
        results[idx] = await fn(items[idx], idx);
      }
    },
  );

  await Promise.all(workers);
  return results;
}

/**
 * 物理单切片更新/覆盖 (Upsert Single Chunk)
 * 若同商户、同文件且同章节路径已存在，则覆盖更新文本与向量，否则插入新记录
 */
export async function upsertDocumentChunk(
  opts: UpsertChunkOptions,
): Promise<string> {
  const drizzle = getDrizzle();
  if (!drizzle) throw new Error("Database connection not ready");

  const embeddingModel = getEmbeddingModel();
  const category = await classifyChunkCategory(
    opts.headerPath,
    opts.chunkText,
    opts.category,
  );
  const summary = await generateContextualSummary({
    fullDocumentTitle: opts.docTitle,
    headerPath: opts.headerPath,
    chunkText: opts.chunkText,
    businessId: opts.businessId,
    documentOutline: opts.documentOutline,
    parentChunk: opts.parentChunk,
  });

  const combinedText = `[Context] ${summary}\n\n[Content] ${opts.chunkText}`;
  const embedding = await embeddingModel.embedQuery(combinedText);
  const serializedEmbedding = JSON.stringify(embedding);
  const contentHash = MarkdownChunker.computeHash(
    opts.headerPath,
    opts.chunkText,
  );

  // 检查是否存在现有同源或同内容切片（防止产生重复数据）
  const existing = await drizzle
    .select({ id: ragDocuments.id })
    .from(ragDocuments)
    .where(
      and(
        eq(ragDocuments.businessId, opts.businessId),
        eq(ragDocuments.chunkText, opts.chunkText),
      ),
    )
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
          contentHash,
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
        contentHash,
        updatedAt: new Date().toISOString(),
      },
    })
    .returning({ id: ragDocuments.id });

  return inserted.id;
}

/**
 * 物理删除源文件对应的所有历史 RAG 切片 (Delete Chunks By Source)
 */
export async function deleteChunksBySource(
  businessId: string,
  sourceUrl: string,
): Promise<number> {
  const drizzle = getDrizzle();
  if (!drizzle) return 0;

  const result = await drizzle
    .delete(ragDocuments)
    .where(
      and(
        eq(ragDocuments.businessId, businessId),
        eq(ragDocuments.sourceUrl, sourceUrl),
      ),
    );

  return result.rowCount ?? 0;
}

/**
 * 高性能大文档差量增量同步 (Incremental Diff Sync with Hash Matching & Concurrency Pool)
 * 针对超大文档：
 * 1. 计算大纲 (Outline) 与每个切片的内容哈希 (SHA-256 Hash)
 * 2. 对比数据库历史切片，未变更切片直接复用（跳过 LLM 和 Embedding 算力消耗）
 * 3. 仅对新增和变更的切片以并发池 (5 并发) 进行 Contextual Retrieval 生成
 * 4. 清理已被删除的废弃切片
 */
export async function syncKnowledgeDocument(
  filePath: string,
  overrideBusinessId?: string,
  concurrency = 5,
): Promise<SyncFileResult> {
  const drizzle = getDrizzle();
  if (!drizzle) {
    return {
      filePath,
      businessId: overrideBusinessId || "ecommerce",
      totalChunks: 0,
      inserted: 0,
      updated: 0,
      unchanged: 0,
      deleted: 0,
    };
  }

  const fileName = path.basename(filePath);
  const rawContent = fs.readFileSync(filePath, "utf-8");
  const { frontmatter, body } = parseFrontmatter(rawContent);

  let businessId = overrideBusinessId || frontmatter.businessId || "ecommerce";
  if (!frontmatter.businessId && !overrideBusinessId) {
    const lower = fileName.toLowerCase();
    if (lower.includes("nike")) businessId = "nike";
    else if (lower.includes("adidas")) businessId = "adidas";
  }

  let docTitle = frontmatter.title || "";
  if (!docTitle) {
    const firstLine = body.split("\n")[0] || "";
    docTitle = firstLine.replace(/^#+\s*/, "").trim() || fileName;
  }

  const explicitCategory = frontmatter.category as RAGCategory | undefined;

  // 1. 提取全局大纲与结构化切片（带 Hash 与父段落）
  const documentOutline = MarkdownChunker.extractOutline(body);
  const chunks = MarkdownChunker.splitMarkdown(body, {
    maxChunkSize: 500,
    category: explicitCategory,
    includeParentChunk: true,
  });

  // 2. 查询已有切片记录
  const existingRows = await drizzle
    .select({
      id: ragDocuments.id,
      chunkText: ragDocuments.chunkText,
      contextualSummary: ragDocuments.contextualSummary,
      embedding: ragDocuments.embedding,
      metadata: ragDocuments.metadata,
    })
    .from(ragDocuments)
    .where(
      and(
        eq(ragDocuments.businessId, businessId),
        eq(ragDocuments.sourceUrl, fileName),
      ),
    );

  const existingMap = new Map<string, (typeof existingRows)[0]>();
  for (const row of existingRows) {
    let rowHash = "";
    if (row.metadata) {
      const meta =
        typeof row.metadata === "string"
          ? JSON.parse(row.metadata)
          : (row.metadata as Record<string, any>);
      rowHash = meta.contentHash || "";
    }
    // 以 contentHash 为主键，若无则以 chunkText 降级比对
    const key = rowHash || row.chunkText;
    existingMap.set(key, row);
  }

  const embeddingModel = getEmbeddingModel();
  const matchedRowIds = new Set<string>();

  let unchangedCount = 0;
  let insertedCount = 0;
  let updatedCount = 0;

  // 3. 区分需要计算的切片与未修改切片
  interface PendingTask {
    chunk: (typeof chunks)[0];
    existingId?: string;
  }

  const tasksToProcess: PendingTask[] = [];

  for (const chunk of chunks) {
    const existing =
      existingMap.get(chunk.contentHash) || existingMap.get(chunk.chunkText);
    if (existing && existing.embedding) {
      // 完全一致，直接标记复用
      matchedRowIds.add(existing.id);
      unchangedCount++;
    } else {
      tasksToProcess.push({ chunk, existingId: existing?.id });
    }
  }

  // 4. 受控并发批处理新增与变更切片
  if (tasksToProcess.length > 0) {
    await mapConcurrent(tasksToProcess, concurrency, async (task) => {
      const { chunk, existingId } = task;
      const category = await classifyChunkCategory(
        chunk.headerPath,
        chunk.chunkText,
        explicitCategory,
      );

      const summary = await generateContextualSummary({
        fullDocumentTitle: docTitle,
        headerPath: chunk.headerPath,
        chunkText: chunk.chunkText,
        businessId,
        documentOutline,
        parentChunk: chunk.parentChunk,
      });

      const combinedText = `[Context] ${summary}\n\n[Content] ${chunk.chunkText}`;
      const embedding = await embeddingModel.embedQuery(combinedText);
      const serializedEmbedding = JSON.stringify(embedding);

      const record = {
        businessId,
        sourceUrl: fileName,
        chunkText: chunk.chunkText,
        contextualSummary: summary,
        embedding: serializedEmbedding,
        metadata: {
          category,
          docTitle,
          headerPath: chunk.headerPath,
          sourceFile: fileName,
          contentHash: chunk.contentHash,
          parentChunk: chunk.parentChunk
            ? chunk.parentChunk.slice(0, 500)
            : undefined,
          updatedAt: new Date().toISOString(),
        },
      };

      if (existingId) {
        await drizzle
          .update(ragDocuments)
          .set(record)
          .where(eq(ragDocuments.id, existingId));
        matchedRowIds.add(existingId);
        updatedCount++;
      } else {
        const [ins] = await drizzle
          .insert(ragDocuments)
          .values(record)
          .returning({ id: ragDocuments.id });
        matchedRowIds.add(ins.id);
        insertedCount++;
      }
    });
  }

  // 5. 清理已废弃的旧切片（严格附带租户隔离约束）
  const obsoleteIds = existingRows
    .map((r) => r.id)
    .filter((id) => !matchedRowIds.has(id));
  let deletedCount = 0;
  if (obsoleteIds.length > 0) {
    const delResult = await drizzle
      .delete(ragDocuments)
      .where(
        and(
          eq(ragDocuments.businessId, businessId),
          inArray(ragDocuments.id, obsoleteIds),
        ),
      );
    deletedCount = delResult.rowCount ?? obsoleteIds.length;
  }

  console.log(
    `[SyncRAG] ⚡ 文档差量同步完成 ${fileName} (商户: ${businessId}, 总切片: ${chunks.length}, 新增: ${insertedCount}, 更新: ${updatedCount}, 复用未变: ${unchangedCount}, 删除废弃: ${deletedCount})`,
  );

  return {
    filePath,
    businessId,
    totalChunks: chunks.length,
    inserted: insertedCount,
    updated: updatedCount,
    unchanged: unchangedCount,
    deleted: deletedCount,
  };
}

/**
 * 热替换整个知识库文件 (Replace Full Knowledge File) - 兼容既有接口
 */
export async function replaceKnowledgeFile(
  filePath: string,
  overrideBusinessId?: string,
): Promise<number> {
  const result = await syncKnowledgeDocument(filePath, overrideBusinessId);
  return result.totalChunks;
}
