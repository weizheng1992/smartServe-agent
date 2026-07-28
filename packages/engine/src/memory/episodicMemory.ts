import { episodicEvents, getDrizzle } from 'db';
import { getEmbeddingModel } from '../llm/callLLMWithRetry';

export interface EpisodicEvent {
  id: string;
  event: string;
  importanceScore: number; // 1-10
  timestamp: Date;
  embedding?: number[];
}

export class EpisodicMemory {
  private userId: string;

  constructor(userId: string) {
    this.userId = userId;
  }

  async addEvent(event: string, importanceScore: number): Promise<void> {
    console.log(`[EpisodicMemory] Added event for user ${this.userId}: "${event}" with importance: ${importanceScore}`);
    const embeddingModel = getEmbeddingModel();
    const embedding = await embeddingModel.embedQuery(event);

    const dbInstance = getDrizzle();
    if (dbInstance) {
      try {
        const serializedEmbedding = JSON.stringify(embedding);
        await dbInstance.insert(episodicEvents).values({
          userId: this.userId,
          content: event,
          embedding: serializedEmbedding,
          importance: importanceScore,
          timestamp: new Date(),
        });
        console.log(`[EpisodicMemory] Stored event directly in PostgreSQL: "${event}"`);
        return;
      } catch (err) {
        console.warn('[EpisodicMemory] Drizzle insertion bypassed due to offline/failed DB.');
      }
    }
  }

  async retrieveEvents(query: string, limit = 3, precomputedEmbedding?: number[]): Promise<EpisodicEvent[]> {
    console.log(`[EpisodicMemory] Retrieving episodic events for user ${this.userId} using query: ${query}`);

    let queryEmbedding = precomputedEmbedding;
    if (!queryEmbedding || queryEmbedding.length === 0) {
      const embeddingModel = getEmbeddingModel();
      queryEmbedding = await embeddingModel.embedQuery(query);
    }

    const dbInstance = getDrizzle();
    if (dbInstance) {
      try {
        const { eq } = require('drizzle-orm');
        // Retrieve all episodic events for the user and perform in-memory cosine similarity calculation in TS.
        const allEvents = await dbInstance
          .select({
            id: episodicEvents.id,
            content: episodicEvents.content,
            importance: episodicEvents.importance,
            embedding: episodicEvents.embedding,
            timestamp: episodicEvents.timestamp,
          })
          .from(episodicEvents)
          .where(eq(episodicEvents.userId, this.userId));

        if (allEvents.length > 0) {
          const scoredEvents = allEvents.map((row: any) => {
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

            return {
              event: {
                id: row.id,
                event: row.content,
                importanceScore: row.importance || 3,
                timestamp: row.timestamp || new Date(),
                embedding: embeddingArray || undefined,
              },
              similarity,
            };
          });

          // Sort descending by similarity
          scoredEvents.sort((a: any, b: any) => b.similarity - a.similarity);

          // 🔍 性能与 Prompt 优化：建立相似度硬阈值过滤（最低 0.60），
          // 剔除风马牛不相及的事件流落入 Prompt 造成上下文膨胀、延迟飙升
          const SIMILARITY_THRESHOLD = 0.6;
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
