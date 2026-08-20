import * as path from 'node:path';
import { ContextualRAG, type ScoredRAGDocument } from './contextualRag';
import { type IngestResult, type RAGCategory, ingestTxtDirectory } from './ingestTxtFiles';
import { type UpsertChunkOptions, deleteChunksBySource, replaceKnowledgeFile, upsertDocumentChunk } from './updateRag';

export interface KnowledgeSearchOptions {
  limit?: number;
  category?: RAGCategory | string;
  precomputedEmbedding?: number[];
}

export class KnowledgeEngine {
  private rag: ContextualRAG;
  public readonly businessId: string;

  constructor(businessId = 'ecommerce') {
    this.businessId = businessId;
    this.rag = new ContextualRAG(businessId);
  }

  /**
   * 🔍 多租户隔离混合检索 (BM25 + Cosine Similarity + RRF Reranking)
   */
  public async search(query: string, options: KnowledgeSearchOptions = {}): Promise<ScoredRAGDocument[]> {
    const limit = options.limit || 2;
    return this.rag.searchRelevantDocs(query, limit, options.precomputedEmbedding, options.category);
  }

  /**
   * 🔄 热替换全量知识文档 (Atomic File Hot Replacement)
   */
  public async replaceFile(filePath: string): Promise<number> {
    return replaceKnowledgeFile(filePath, this.businessId);
  }

  /**
   * 📝 物理更新/插入单条知识切片 (Single Chunk Upsert)
   */
  public async upsertChunk(opts: Omit<UpsertChunkOptions, 'businessId'>): Promise<string> {
    return upsertDocumentChunk({
      ...opts,
      businessId: this.businessId,
    });
  }

  /**
   * 🗑️ 物理清理对应源文件的废弃切片 (Delete Chunks By Source)
   */
  public async deleteSource(sourceUrl: string): Promise<number> {
    return deleteChunksBySource(this.businessId, sourceUrl);
  }

  /**
   * 📁 批量落盘解析目录下的 Markdown / TXT 知识库 (Bulk Directory Ingestion)
   */
  public async ingestDirectory(dirPath?: string): Promise<IngestResult[]> {
    const targetDir = dirPath || path.resolve(__dirname, '../../../../docs/knowledge');
    return ingestTxtDirectory(targetDir);
  }
}
