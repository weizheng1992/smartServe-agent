import * as crypto from 'node:crypto';

/**
 * 原生 Markdown 语义与操作步骤切分器 (Native Markdown & Step Chunker)
 * 专为商店信息、商品知识与 SOP 操作指南设计的结构化段落保护切割工具
 */

export interface ChunkResult {
  chunkText: string;
  headerPath: string; // e.g. "Nike 官方店 > 营业时间与地址"
  category?: string;
  stepCount?: number;
  contentHash: string; // SHA-256 差量比对指纹
  parentChunk?: string; // 所属完整章节段落（父块上下文）
  isTable?: boolean;
  isCodeBlock?: boolean;
}

export interface ChunkerOptions {
  maxChunkSize?: number; // 字符数上限，默认 600
  overlap?: number; // 字符重叠度，默认 50
  category?: string;
  includeParentChunk?: boolean; // 是否携带父级完整章节段落
}

export interface MarkdownSection {
  title: string;
  level: number;
  headerPath: string;
  content: string;
}

export class MarkdownChunker {
  /**
   * 计算切片指纹哈希（用于差量比对与增量更新）
   */
  public static computeHash(headerPath: string, text: string): string {
    return crypto.createHash('sha256').update(`${headerPath}::${text.trim()}`).digest('hex');
  }

  /**
   * 提取 Markdown 文档的章节大纲树结构（用于超长文档的整体大纲概括）
   */
  public static extractOutline(markdownText: string): string {
    if (!markdownText) return '';
    const lines = markdownText.split('\n');
    const outlineLines: string[] = [];

    for (const line of lines) {
      const headerMatch = line.match(/^(#{1,6})\s+(.+)$/);
      if (headerMatch) {
        const indent = '  '.repeat(Math.max(0, headerMatch[1].length - 1));
        outlineLines.push(`${indent}- ${headerMatch[2].trim()}`);
      }
    }

    return outlineLines.join('\n');
  }

  /**
   * 将 Markdown 格式的知识库文档智能切割为语义与步骤完整的 Chunk 切片
   * 包含表格保护、代码块保护与步骤完整性保护
   */
  public static splitMarkdown(markdownText: string, options: ChunkerOptions = {}): ChunkResult[] {
    const maxChunkSize = options.maxChunkSize || 600;
    const category = options.category || 'general';
    const includeParent = options.includeParentChunk ?? true;

    if (!markdownText || typeof markdownText !== 'string') {
      return [];
    }

    const lines = markdownText.split('\n');
    const results: ChunkResult[] = [];

    let currentHeaders: string[] = [];
    let currentChunkLines: string[] = [];
    let currentLength = 0;
    let inCodeBlock = false;
    let sectionLines: string[] = [];

    const flushChunk = () => {
      if (currentChunkLines.length === 0) return;
      const text = currentChunkLines.join('\n').trim();
      if (text.length > 0) {
        const headerPath = currentHeaders.join(' > ') || '通用说明';
        const stepMatches = text.match(/^\s*\d+\.\s+/gm);
        const isTable =
          text.includes('|') && text.split('\n').some((l) => l.trim().startsWith('|') && l.trim().endsWith('|'));
        const isCodeBlock = text.startsWith('```') && text.endsWith('```');

        const parentChunk = includeParent && sectionLines.length > 0 ? sectionLines.join('\n').trim() : undefined;
        const contentHash = MarkdownChunker.computeHash(headerPath, text);

        results.push({
          chunkText: text,
          headerPath,
          category,
          stepCount: stepMatches ? stepMatches.length : 0,
          contentHash,
          parentChunk,
          isTable,
          isCodeBlock,
        });
      }
      currentChunkLines = [];
      currentLength = 0;
    };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // 检测代码块边界 (```)
      if (line.trim().startsWith('```')) {
        inCodeBlock = !inCodeBlock;
      }

      const headerMatch = !inCodeBlock ? line.match(/^(#{1,6})\s+(.+)$/) : null;
      if (headerMatch) {
        // 遇到新标题时，冲刷上一个 Chunk 与章节
        const level = headerMatch[1].length;
        const headerTitle = headerMatch[2].trim();

        flushChunk();

        // 保持标题层级（H1 替换 [0], H2 替换 [1]）
        currentHeaders = currentHeaders.slice(0, level - 1);
        currentHeaders[level - 1] = headerTitle;
        sectionLines = [line];
        continue;
      }

      sectionLines.push(line);

      // 表格保护：如果当前行是 Markdown 表格行，并且下一个切片即将超限，检查表格是否能尽量聚集
      const isTableRow = line.trim().startsWith('|') && line.trim().endsWith('|');

      // 检查加入当前行是否会超出 maxChunkSize（如果在代码块内且未超大，优先保护代码块不截断）
      if (!inCodeBlock && currentLength + line.length > maxChunkSize && currentChunkLines.length > 0) {
        // 如果是表格连续行且当前块尚在合理缓冲内（< maxChunkSize * 1.3），允许稍作延展保持表格完整
        if (isTableRow && currentLength < maxChunkSize * 1.3) {
          currentChunkLines.push(line);
          currentLength += line.length + 1;
          continue;
        }
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
