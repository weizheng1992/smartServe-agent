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
}

export interface ChunkResult {
  chunkIndex: number;
  chunkText: string;
  startOffset?: number;
  endOffset?: number;
}

export interface ChunkDocumentParams {
  text: string;
  targetChunkSize?: number;
  overlap?: number;
}

export interface BuildContextualPromptParams {
  fullDocumentText: string;
  chunkText: string;
  businessId: string;
  brandName?: string;
}

export interface PrepareRagRecordsParams {
  businessId: string;
  sourceUrl?: string;
  chunks: Array<{ chunkIndex: number; chunkText: string }>;
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
export async function parseDocumentText(params: ParseDocumentParams): Promise<ParsedDocument> {
  const { content, filename } = params;
  const rawText = typeof content === 'string' ? content : content.toString('utf8');

  // 提取首个 Markdown 一级标题或文件名作为文档标题
  const titleMatch = rawText.match(/^#\s+(.+)$/m);
  const title = titleMatch ? titleMatch[1].trim() : filename.replace(/\.[^/.]+$/, '');

  const lines = rawText.split('\n');

  return {
    title,
    filename,
    rawText: rawText.trim(),
    lineCount: lines.length,
    charCount: rawText.length,
  };
}

/**
 * 递归边界感知分块（按段落与重叠切分）
 */
export function chunkDocumentText(params: ChunkDocumentParams): ChunkResult[] {
  const { text, targetChunkSize = 600, overlap = 100 } = params;
  const cleanedText = text.trim();

  if (!cleanedText) return [];

  // 优先按段落切分
  const paragraphs = cleanedText
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  const chunks: ChunkResult[] = [];

  let currentChunk = '';
  let chunkIdx = 0;

  for (const paragraph of paragraphs) {
    if ((currentChunk + '\n\n' + paragraph).length > targetChunkSize && currentChunk.length > 0) {
      chunks.push({
        chunkIndex: chunkIdx++,
        chunkText: currentChunk.trim(),
      });

      // 保留 overlap 长度的尾部
      const overlapText = currentChunk.slice(-overlap);
      currentChunk = overlapText + '\n\n' + paragraph;
    } else {
      currentChunk = currentChunk ? `${currentChunk}\n\n${paragraph}` : paragraph;
    }
  }

  if (currentChunk.trim().length > 0) {
    chunks.push({
      chunkIndex: chunkIdx++,
      chunkText: currentChunk.trim(),
    });
  }

  return chunks;
}

/**
 * 构建 Anthropic 标准的 Contextual Retrieval 提示词
 */
export function buildContextualSummaryPrompt(params: BuildContextualPromptParams): string {
  const { fullDocumentText, chunkText, businessId, brandName = businessId } = params;

  return `<document>
${fullDocumentText}
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
export function prepareRagDocumentRecords(params: PrepareRagRecordsParams): PreparedRagDocument[] {
  const { businessId, sourceUrl, chunks, contextualSummaries = [], metadata = {} } = params;

  return chunks.map((chunk, idx) => ({
    businessId,
    sourceUrl,
    chunkText: chunk.chunkText,
    contextualSummary: contextualSummaries[idx] || undefined,
    metadata: {
      ...metadata,
      chunkIndex: chunk.chunkIndex,
      totalChunks: chunks.length,
      ingestedAt: new Date().toISOString(),
    },
  }));
}
