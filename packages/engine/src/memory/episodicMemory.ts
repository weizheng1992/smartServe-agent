import { episodicEvents, getDrizzle } from 'db';
import { getEmbeddingModel } from '../llm/callLLMWithRetry';

export interface EpisodicEvent {
  id: string;
  event: string;
  importanceScore: number; // 1-10
  timestamp: Date;
  embedding?: number[];
  scope?: 'global' | 'tenant';
  businessId?: string;
}

export class EpisodicMemory {
  private userId: string;
  private businessId?: string;

  constructor(userId: string, businessId?: string) {
    this.userId = userId;
    this.businessId = businessId;
  }

  async addEvent(
    event: string,
    importanceScore: number,
    scope: 'global' | 'tenant' = 'tenant',
    businessId?: string,
  ): Promise<void> {
    if (!this.userId) {
      console.warn('[EpisodicMemory] Cannot add event without userId');
      return;
    }
    const targetBizId = scope === 'tenant' ? businessId || this.businessId || 'ecommerce' : null;

    console.log(
      `[EpisodicMemory] Added event for user ${this.userId} (Scope: ${scope}, Biz: ${targetBizId}): "${event}" with importance: ${importanceScore}`,
    );
    const embeddingModel = getEmbeddingModel();
    const embedding = await embeddingModel.embedQuery(event);

    const dbInstance = getDrizzle();
    if (dbInstance) {
      try {
        const serializedEmbedding = JSON.stringify(embedding);
        await dbInstance.insert(episodicEvents).values({
          userId: this.userId,
          businessId: targetBizId,
          scope: scope,
          content: event,
          embedding: serializedEmbedding,
          importance: importanceScore,
          timestamp: new Date(),
        });
        console.log(`[EpisodicMemory] Stored event directly in PostgreSQL [Scope: ${scope}]: "${event}"`);
        return;
      } catch (err) {
        console.warn('[EpisodicMemory] Drizzle insertion bypassed due to offline/failed DB.');
      }
    }
  }

  async retrieveEvents(query: string, limit = 3, precomputedEmbedding?: number[]): Promise<EpisodicEvent[]> {
    if (!this.userId) {
      return [];
    }
    console.log(`[EpisodicMemory] Retrieving episodic events for user ${this.userId} using query: ${query}`);

    let queryEmbedding = precomputedEmbedding;
    if (!queryEmbedding || queryEmbedding.length === 0) {
      const embeddingModel = getEmbeddingModel();
      queryEmbedding = await embeddingModel.embedQuery(query);
    }

    const dbInstance = getDrizzle();
    if (dbInstance) {
      try {
        const { eq, desc } = require('drizzle-orm');
        // 限制最多只读取最近的 50 条事件，避免历史会话过多时进行海量全表扫描与无谓的日志打印
        const allEvents = await dbInstance
          .select({
            id: episodicEvents.id,
            content: episodicEvents.content,
            importance: episodicEvents.importance,
            embedding: episodicEvents.embedding,
            timestamp: episodicEvents.timestamp,
            scope: episodicEvents.scope,
            businessId: episodicEvents.businessId,
          })
          .from(episodicEvents)
          .where(eq(episodicEvents.userId, this.userId))
          .orderBy(desc(episodicEvents.timestamp))
          .limit(50);

        // 🛡️ 多租户情景隔离与防投毒 (Dual-Tier Scoped Episodic Isolation)
        const tenantEvents = allEvents.filter((row: any) => {
          if (!row.scope || row.scope === 'global') {
            return true;
          }
          if (row.scope === 'tenant') {
            if (this.businessId && this.businessId !== 'ecommerce') {
              return row.businessId === this.businessId;
            }
            return !row.businessId || row.businessId === 'ecommerce' || row.businessId === this.businessId;
          }
          return false;
        });

        if (tenantEvents.length > 0) {
          const scoredEvents = tenantEvents.map((row: any) => {
            let embeddingArray: number[] | null = null;
            if (row.embedding) {
              try {
                embeddingArray = typeof row.embedding === 'string' ? JSON.parse(row.embedding) : row.embedding;
              } catch (e) {
                console.warn('[EpisodicMemory] Failed to parse embedding JSON:', e);
              }
            }

            let similarity = 0;
            if (embeddingArray && Array.isArray(embeddingArray) && embeddingArray.length === queryEmbedding.length) {
              // cosine similarity = (A . B) / (||A|| * ||B||)
              let dotProduct = 0;
              let normA = 0;
              let normB = 0;
              for (let i = 0; i < queryEmbedding.length; i++) {
                dotProduct += queryEmbedding[i] * embeddingArray[i];
                normA += queryEmbedding[i] * queryEmbedding[i];
                normB += embeddingArray[i] * embeddingArray[i];
              }
              const denominator = Math.sqrt(normA) * Math.sqrt(normB);
              similarity = denominator === 0 ? 0 : dotProduct / denominator;
            }

            // 结合关键词重合度做混合打分
            const queryTokens = query
              .toLowerCase()
              .split(/[\s,，、。!！?？]+/)
              .filter((t) => t.length >= 2);
            let keywordMatches = 0;
            for (const token of queryTokens) {
              if (row.content.toLowerCase().includes(token)) {
                keywordMatches++;
              }
            }
            const keywordScore = queryTokens.length > 0 ? (keywordMatches / queryTokens.length) * 0.95 : 0;
            const effectiveScore = Math.max(similarity, keywordScore);

            return {
              event: {
                id: row.id,
                event: row.content,
                importanceScore: row.importance || 3,
                timestamp: row.timestamp || new Date(),
                embedding: embeddingArray || undefined,
                scope: row.scope || 'global',
                businessId: row.businessId || undefined,
              },
              similarity: effectiveScore,
            };
          });

          // Sort descending by similarity
          scoredEvents.sort((a, b) => b.similarity - a.similarity);

          // 🔍 性能与 Prompt 优化：建立相似度硬阈值过滤（最低 0.55），
          // 剔除风马牛不相及的事件流落入 Prompt 造成上下文膨胀、延迟飙升
          const SIMILARITY_THRESHOLD = 0.55;
          const filteredEvents = scoredEvents.filter((item: any) => {
            const isPassed = item.similarity >= SIMILARITY_THRESHOLD;
            if (!isPassed && item.similarity > 0) {
              console.log(
                `[EpisodicMemory Filter] Event irrelevant, similarity ${item.similarity.toFixed(3)} below ${SIMILARITY_THRESHOLD}: "${item.event.event}"`,
              );
            }
            return isPassed;
          });

          // Limit and return top limit
          return filteredEvents.slice(0, limit).map((se: any) => se.event);
        }
      } catch (err) {
        console.warn('[EpisodicMemory] TS-based cosine similarity search bypassed due to offline/failed DB.', err);
      }
    }

    return [];
  }
}
