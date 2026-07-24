import { getDrizzle, longMemoryFacts } from 'db';
import { getEmbeddingModel } from '../llm/callLLMWithRetry';

export interface LongMemoryFact {
  id: string;
  fact: string;
  category: string;
  timestamp: string;
  embedding?: number[];
}

export class LongMemory {
  private userId: string;

  constructor(userId: string) {
    this.userId = userId;
  }

  async extractAndStoreFact(conversationText: string): Promise<void> {
    console.log(`[LongMemory] Extracting facts from text for user ${this.userId}`);
    const lines = conversationText
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    const embeddingModel = getEmbeddingModel();

    for (const line of lines) {
      if (
        line.toLowerCase().includes('user prefers') ||
        line.toLowerCase().includes('prefers') ||
        line.toLowerCase().includes('fact:')
      ) {
        const factText = line.replace(/^(fact:)/i, '').trim();
        const embedding = await embeddingModel.embedQuery(factText);

        const dbInstance = getDrizzle();
        if (dbInstance) {
          try {
            const serializedEmbedding = JSON.stringify(embedding);
            await dbInstance.insert(longMemoryFacts).values({
              userId: this.userId,
              fact: factText,
              embedding: serializedEmbedding,
              type: 'preference',
              createdAt: new Date(),
            });
            console.log(`[LongMemory] Extracted and stored fact directly in PostgreSQL: "${factText}"`);
          } catch (err) {
            console.warn('[LongMemory] Drizzle insertion bypassed due to offline/failed DB.');
          }
        }
      }
    }
  }

  async searchRelevantFacts(query: string): Promise<LongMemoryFact[]> {
    console.log(`[LongMemory] Searching relevant facts for user ${this.userId} using query: ${query}`);
    const embeddingModel = getEmbeddingModel();
    const queryEmbedding = await embeddingModel.embedQuery(query);

    const dbInstance = getDrizzle();
    if (dbInstance) {
      try {
        const { eq } = require('drizzle-orm');
        // Retrieve all facts for the user and perform in-memory cosine similarity calculation in TS.
        const allFacts = await dbInstance
          .select({
            id: longMemoryFacts.id,
            fact: longMemoryFacts.fact,
            type: longMemoryFacts.type,
            embedding: longMemoryFacts.embedding,
            createdAt: longMemoryFacts.createdAt,
          })
          .from(longMemoryFacts)
          .where(eq(longMemoryFacts.userId, this.userId));

        if (allFacts.length > 0) {
          const scoredFacts = allFacts.map((row: any) => {
            let embeddingArray: number[] | null = null;
            if (row.embedding) {
              try {
                embeddingArray = typeof row.embedding === 'string' ? JSON.parse(row.embedding) : row.embedding;
              } catch (e) {
                console.warn('[LongMemory] Failed to parse embedding JSON:', e);
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
              fact: {
                id: row.id,
                fact: row.fact,
                category: row.type || 'preference',
                timestamp: row.createdAt ? row.createdAt.toISOString() : new Date().toISOString(),
                embedding: embeddingArray || undefined,
              },
              similarity,
            };
          });

          // 按照余弦相似度（降序）排序
          scoredFacts.sort((a: any, b: any) => b.similarity - a.similarity);

          // 🔍 性能与 Prompt 优化：建立相似度硬阈值过滤（最低 0.65），
          // 彻底拒绝无关的、低置信度事实被一股脑塞进 Prompt 混淆大模型认知并造成 Token 浪费！
          const SIMLIARITY_THRESHOLD = 0.65;
          const filteredFacts = scoredFacts.filter((item: any) => {
            const isPassed = item.similarity >= SIMLIARITY_THRESHOLD;
            if (!isPassed && item.similarity > 0) {
              console.log(
                `[LongMemory Filter] Fact irrelevant, similarity ${item.similarity.toFixed(3)} below ${SIMLIARITY_THRESHOLD}: "${item.fact.fact}"`,
              );
            }
            return isPassed;
          });

          // 限制返回最相关的 Top 5，保证 Prompt 极简、清爽
          return filteredFacts.slice(0, 5).map((sf: any) => sf.fact);
        }
      } catch (err) {
        console.warn('[LongMemory] TS-based cosine similarity search bypassed due to offline/failed DB.', err);
      }
    }

    return [];
  }
}
