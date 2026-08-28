import { MarkdownChunker } from "./chunker";

export interface ParseDocumentParams {
  content: string | Buffer;
  filename: string;
  mimeType?: string;
}

export interface ParsedDocument {
  title: string;
  filename: string;
  rawText: string;
  lineCount: number;
  charCount: number;
  outline?: string;
}

export interface ChunkResult {
  chunkIndex: number;
  chunkText: string;
  startOffset?: number;
  endOffset?: number;
  contentHash?: string;
  headerPath?: string;
  parentChunk?: string;
}

export interface ChunkDocumentParams {
  text: string;
  targetChunkSize?: number;
  overlap?: number;
  headerPath?: string;
}

export interface BuildContextualPromptParams {
  fullDocumentText?: string;
  documentOutline?: string;
  sectionContext?: string;
  chunkText: string;
  businessId: string;
  brandName?: string;
}

export interface PrepareRagRecordsParams {
  businessId: string;
  sourceUrl?: string;
  chunks: Array<{
    chunkIndex: number;
    chunkText: string;
    contentHash?: string;
    headerPath?: string;
  }>;
  contextualSummaries?: string[];
  metadata?: Record<string, unknown>;
}

export interface PreparedRagDocument {
  businessId: string;
  sourceUrl?: string;
  chunkText: string;
  contextualSummary?: string;
  metadata?: Record<string, unknown>;
}

/**
 * 解析并提取文档纯文本与元数据（支持 Markdown, TXT, 规整文本）
 */
export async function parseDocumentText(
  params: ParseDocumentParams,
): Promise<ParsedDocument> {
  const { content, filename } = params;
  const rawText =
    typeof content === "string" ? content : content.toString("utf8");

  // 提取首个 Markdown 一级标题或文件名作为文档标题
  const titleMatch = rawText.match(/^#\s+(.+)$/m);
  const title = titleMatch
    ? titleMatch[1].trim()
    : filename.replace(/\.[^/.]+$/, "");

  const lines = rawText.split("\n");
  const outline = MarkdownChunker.extractOutline(rawText);

  return {
    title,
    filename,
    rawText: rawText.trim(),
    lineCount: lines.length,
    charCount: rawText.length,
    outline,
  };
}

/**
 * 递归边界感知分块（按段落与重叠切分）
 */
export function chunkDocumentText(params: ChunkDocumentParams): ChunkResult[] {
  const {
    text,
    targetChunkSize = 600,
    overlap = 100,
    headerPath = "通用说明",
  } = params;
  const cleanedText = text.trim();

  if (!cleanedText) return [];

  // 优先按段落切分
  const paragraphs = cleanedText
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  const chunks: ChunkResult[] = [];

  let currentChunk = "";
  let chunkIdx = 0;

  for (const paragraph of paragraphs) {
    if (
      (currentChunk + "\n\n" + paragraph).length > targetChunkSize &&
      currentChunk.length > 0
    ) {
      const chunkStr = currentChunk.trim();
      const contentHash = MarkdownChunker.computeHash(headerPath, chunkStr);

      chunks.push({
        chunkIndex: chunkIdx++,
        chunkText: chunkStr,
        contentHash,
        headerPath,
      });

      // 保留 overlap 长度的尾部
      const overlapText = currentChunk.slice(-overlap);
      currentChunk = overlapText + "\n\n" + paragraph;
    } else {
      currentChunk = currentChunk
        ? `${currentChunk}\n\n${paragraph}`
        : paragraph;
    }
  }

  if (currentChunk.trim().length > 0) {
    const chunkStr = currentChunk.trim();
    const contentHash = MarkdownChunker.computeHash(headerPath, chunkStr);

    chunks.push({
      chunkIndex: chunkIdx++,
      chunkText: chunkStr,
      contentHash,
      headerPath,
    });
  }

  return chunks;
}

/**
 * 构建 Anthropic 标准的 Contextual Retrieval 提示词
 * 支持超大文档的分层模式（大纲 + 局部章节上下文）与标准全篇模式
 */
export function buildContextualSummaryPrompt(
  params: BuildContextualPromptParams,
): string {
  const {
    fullDocumentText,
    documentOutline,
    sectionContext,
    chunkText,
    businessId,
    brandName = businessId,
  } = params;

  // 如果提供了 documentOutline 或 fullDocumentText 超过 3000 字符，使用分层上下文提示词
  if (documentOutline || (fullDocumentText && fullDocumentText.length > 3000)) {
    const outline = documentOutline || fullDocumentText?.slice(0, 1000);
    return `<document_outline>
${outline}
</document_outline>
${sectionContext ? `<section_context>\n${sectionContext}\n</section_context>\n` : ""}
Here is the chunk we want to situate within the document for merchant brand [${brandName}]:
<chunk>
${chunkText}
</chunk>

Please give a concise 50-80 words situated context summary in Chinese or English explaining how this chunk fits within the overall document and what store policies, product conditions, or workflows it specifies. Answer with only the context summary text.`;
  }

  return `<document>
${fullDocumentText || ""}
</document>

Here is the chunk we want to situate within the whole document for merchant brand [${brandName}]:
<chunk>
${chunkText}
</chunk>

Please give a concise 50-80 words situated context summary in Chinese or English explaining how this chunk fits within the overall document and what store policies, product conditions, or workflows it specifies. Answer with only the context summary text.`;
}

/**
 * 组装与 Drizzle ORM ragDocuments 表对齐的实体记录
 */
export function prepareRagDocumentRecords(
  params: PrepareRagRecordsParams,
): PreparedRagDocument[] {
  const {
    businessId,
    sourceUrl,
    chunks,
    contextualSummaries = [],
    metadata = {},
  } = params;

  return chunks.map((chunk, idx) => ({
    businessId,
    sourceUrl,
    chunkText: chunk.chunkText,
    contextualSummary: contextualSummaries[idx] || undefined,
    metadata: {
      ...metadata,
      chunkIndex: chunk.chunkIndex,
      totalChunks: chunks.length,
      contentHash: chunk.contentHash,
      headerPath: chunk.headerPath,
      ingestedAt: new Date().toISOString(),
    },
  }));
}
