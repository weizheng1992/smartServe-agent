import { Injectable, NotFoundException } from '@nestjs/common';
import { getDrizzle, ragDocuments } from 'db';
import { and, desc, eq } from 'drizzle-orm';
import { ContextualRAG } from 'engine';

export interface RagDocumentItem {
  id: string;
  businessId: string;
  docTitle?: string;
  title?: string;
  category?: string;
  content?: string;
  chunkText: string;
  tokenCount?: number;
  sourceUrl?: string;
  contextualSummary?: string;
  metadata?: Record<string, unknown>;
  createdAt?: string;
  updatedAt?: string;
}

@Injectable()
export class RagService {
  async getDocuments(tenantId?: string): Promise<RagDocumentItem[]> {
    const drizzle = getDrizzle();
    const query =
      tenantId && tenantId !== 'all'
        ? drizzle
            .select()
            .from(ragDocuments)
            .where(eq(ragDocuments.businessId, tenantId))
            .orderBy(desc(ragDocuments.createdAt))
        : drizzle.select().from(ragDocuments).orderBy(desc(ragDocuments.createdAt));

    const rows = await query;
    return (rows || []).map((r) => {
      const meta = (r.metadata as Record<string, unknown>) || {};
      const docTitle =
        (meta.title as string) ||
        (meta.docTitle as string) ||
        r.sourceUrl ||
        (r.businessId === 'nike'
          ? 'Nike 官方售后与质保政策'
          : r.businessId === 'adidas'
            ? 'Adidas 品牌服务与退换细则'
            : '官方通用商城知识文档');
      const category = (meta.category as string) || (r.businessId === 'nike' ? '售后政策' : '商品知识');
      return {
        id: r.id,
        businessId: r.businessId,
        docTitle,
        title: docTitle,
        category,
        content: r.chunkText,
        chunkText: r.chunkText,
        tokenCount: Math.ceil((r.chunkText?.length || 0) * 1.3),
        sourceUrl: r.sourceUrl || undefined,
        contextualSummary: r.contextualSummary || undefined,
        metadata: meta,
        createdAt: r.createdAt ? new Date(r.createdAt).toISOString().split('T')[0] : '2026-02-23',
        updatedAt: r.createdAt ? new Date(r.createdAt).toISOString().split('T')[0] : '2026-02-23',
      };
    });
  }

  async addDocument(doc: {
    businessId: string;
    sourceUrl?: string;
    chunkText?: string;
    content?: string;
    title?: string;
    docTitle?: string;
    category?: string;
    contextualSummary?: string;
    metadata?: Record<string, unknown>;
  }): Promise<RagDocumentItem> {
    const drizzle = getDrizzle();
    const text = doc.chunkText || doc.content || '';
    const meta = {
      ...(doc.metadata || {}),
      title: doc.title || doc.docTitle || '知识文档',
      category: doc.category || '通用政策',
    };
    const [inserted] = await drizzle
      .insert(ragDocuments)
      .values({
        businessId: doc.businessId,
        sourceUrl: doc.sourceUrl,
        chunkText: text,
        contextualSummary: doc.contextualSummary || text.slice(0, 50),
        metadata: meta,
      })
      .returning();

    return {
      id: inserted.id,
      businessId: inserted.businessId,
      docTitle: meta.title,
      title: meta.title,
      category: meta.category,
      content: inserted.chunkText,
      chunkText: inserted.chunkText,
      tokenCount: Math.ceil((inserted.chunkText?.length || 0) * 1.3),
      sourceUrl: inserted.sourceUrl || undefined,
      contextualSummary: inserted.contextualSummary || undefined,
      metadata: meta,
      createdAt: inserted.createdAt ? new Date(inserted.createdAt).toISOString().split('T')[0] : '2026-02-23',
      updatedAt: inserted.createdAt ? new Date(inserted.createdAt).toISOString().split('T')[0] : '2026-02-23',
    };
  }

  async deleteDocument(id: string, tenantId?: string): Promise<boolean> {
    const drizzle = getDrizzle();
    const cond =
      tenantId && tenantId !== 'all'
        ? and(eq(ragDocuments.id, id as any), eq(ragDocuments.businessId, tenantId))
        : eq(ragDocuments.id, id as any);

    const result = await drizzle.delete(ragDocuments).where(cond).returning();
    if (!result || result.length === 0) {
      throw new NotFoundException({
        code: 'DOCUMENT_NOT_FOUND',
        message: `Document with ID '${id}' not found in database`,
      });
    }
    return true;
  }

  async queryKnowledge(query: string, tenantId?: string) {
    const bizId = tenantId && tenantId !== 'all' ? tenantId : 'ecommerce';
    const rag = new ContextualRAG(bizId);
    const searchResults = await rag.searchRelevantDocs(query, 5);

    if (searchResults && searchResults.length > 0) {
      return {
        query,
        tenantId: bizId,
        matches: searchResults.map((r) => ({
          id: r.id,
          businessId: r.businessId,
          chunkText: r.chunkText,
          contextualSummary: r.contextualSummary,
          score: r.similarity,
        })),
      };
    }

    const docs = await this.getDocuments(tenantId);
    return {
      query,
      tenantId: tenantId || 'all',
      matches: docs.slice(0, 3).map((d) => ({
        id: d.id,
        businessId: d.businessId,
        chunkText: d.chunkText,
        contextualSummary: d.contextualSummary,
        score: 0.75,
      })),
    };
  }
}
