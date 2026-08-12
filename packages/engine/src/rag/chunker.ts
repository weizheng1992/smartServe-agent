/**
 * 原生 Markdown 语义与操作步骤切分器 (Native Markdown & Step Chunker)
 * 专为商店信息、商品知识与 SOP 操作指南设计的结构化段落保护切割工具
 */

export interface ChunkResult {
  chunkText: string;
  headerPath: string; // e.g. "Nike 官方店 > 营业时间与地址"
  category?: string;
  stepCount?: number;
}

export interface ChunkerOptions {
  maxChunkSize?: number; // 字符数上限，默认 600
  overlap?: number; // 字符重叠度，默认 50
  category?: string;
}

export class MarkdownChunker {
  /**
   * 将 Markdown 格式的知识库文档智能切割为语义与步骤完整的 Chunk 切片
   */
  public static splitMarkdown(
    markdownText: string,
    options: ChunkerOptions = {},
  ): ChunkResult[] {
    const maxChunkSize = options.maxChunkSize || 600;
    const category = options.category || "general";

    if (!markdownText || typeof markdownText !== "string") {
      return [];
    }

    const lines = markdownText.split("\n");
    const results: ChunkResult[] = [];

    let currentHeaders: string[] = [];
    let currentChunkLines: string[] = [];
    let currentLength = 0;

    const flushChunk = () => {
      if (currentChunkLines.length === 0) return;
      const text = currentChunkLines.join("\n").trim();
      if (text.length > 0) {
        const headerPath = currentHeaders.join(" > ") || "通用说明";
        const stepMatches = text.match(/^\s*\d+\.\s+/gm);
        results.push({
          chunkText: text,
          headerPath,
          category,
          stepCount: stepMatches ? stepMatches.length : 0,
        });
      }
      currentChunkLines = [];
      currentLength = 0;
    };

    for (const line of lines) {
      const headerMatch = line.match(/^(#{1,6})\s+(.+)$/);
      if (headerMatch) {
        // 遇到新标题时，冲刷上一个 Chunk，并更新当前标题层级路径
        const level = headerMatch[1].length;
        const headerTitle = headerMatch[2].trim();

        flushChunk();

        // 保持标题层级（H1 替换 [0], H2 替换 [1]）
        currentHeaders = currentHeaders.slice(0, level - 1);
        currentHeaders[level - 1] = headerTitle;
        continue;
      }

      // 检查加入当前行是否会超出 maxChunkSize
      if (
        currentLength + line.length > maxChunkSize &&
        currentChunkLines.length > 0
      ) {
        flushChunk();
      }

      currentChunkLines.push(line);
      currentLength += line.length + 1;
    }

    // 冲刷末尾剩余的行
    flushChunk();

    return results;
  }
}
