import { getDrizzle, ragDocuments } from 'db';
import { getEmbeddingModel } from '../llm/callLLMWithRetry';

export interface ScoredRAGDocument {
  id: string;
  businessId: string;
  chunkText: string;
  contextualSummary: string;
  similarity: number;
}

export class ContextualRAG {
  private businessId: string;

  constructor(businessId: string) {
    this.businessId = businessId;
  }

  // Self-healing / self-seeding to ensure demo documents always exist
  private async ensureSeedData(): Promise<void> {
    const drizzle = getDrizzle();
    if (!drizzle) return;

    try {
      const existing = await drizzle.select({ id: ragDocuments.id }).from(ragDocuments).limit(1);

      if (existing.length === 0) {
        console.log('[RAG] 📦 检测到 RAG 知识库为空，启动自动高保真 Contextual RAG 数据自愈注入...');
        const embeddingModel = getEmbeddingModel();

        const seedDocs = [
          {
            businessId: 'ecommerce',
            chunkText:
              '对于我们电商主站的订单，普通用户享有自签收之日起 7 天无理由退换货权益。退回的商品必须保持吊牌完整、未拆封且不影响二次销售。非质量问题的退货由买家自行承担寄回运费。',
            contextualSummary: '这段切片描述了电商主站（ecommerce）标准 7 天无理由退换货的前提条件与退货运费归属政策。',
          },
          {
            businessId: 'nike',
            chunkText:
              'Nike 会员专属福利：支持自订单购买之日起 30 天超长无理由退换货。即使已经拆除吊牌或进行过试穿，只要鞋底无明显磨损，均可享受免费原路退款。退款通过顺丰速运免费寄回。',
            contextualSummary:
              '这段切片详细说明了 Nike 会员尊享的 30 天无损无理由退货、已拆吊牌退货政策以及顺丰寄回服务。',
          },
          {
            businessId: 'adidas',
            chunkText:
              'Adidas 支持签收后 14 天退换货。所有商品必须保留原始包装盒与防伪扣，试穿时请勿弄脏鞋底。退货需要通过官方微信小程序预约快递员上门取件，不支持自行寄送。',
            contextualSummary:
              '这段切片详细规定了 Adidas 的 14 天退换货时效、原始防伪包装要求，以及微信小程序预约取件的硬性物流约束。',
          },
        ];

        for (const doc of seedDocs) {
          const combinedText = `[Context] ${doc.contextualSummary}\n\n[Content] ${doc.chunkText}`;
          const embedding = await embeddingModel.embedQuery(combinedText);
          const serializedEmbedding = JSON.stringify(embedding);

          await drizzle.insert(ragDocuments).values({
            businessId: doc.businessId,
            chunkText: doc.chunkText,
            contextualSummary: doc.contextualSummary,
            embedding: serializedEmbedding,
            metadata: { category: 'refund_policy', version: '1.0' },
          });
        }
        console.log('[RAG] ✅ Contextual RAG 演示数据自动注入成功！已永久落盘 Postgres 物理表。');
      }
    } catch (err) {
      console.warn('[RAG] Self-healing seed failed (possibly due to offline/mocked DB):', err);
    }
  }

  async searchRelevantDocs(query: string, limit = 2): Promise<ScoredRAGDocument[]> {
    console.log(`[RAG] 🔍 SaaS 租户隔离检索启动：租户 [${this.businessId}]，检索提问 [${query}]...`);

    // Ensure seed data exists in the database
    await this.ensureSeedData();

    const embeddingModel = getEmbeddingModel();
    let queryEmbedding: number[] = [];
    try {
      queryEmbedding = await embeddingModel.embedQuery(query);
    } catch (err) {
      console.error('[RAG] Failed to generate embedding for search query:', err);
      return [];
    }

    const drizzle = getDrizzle();
    if (!drizzle) {
      console.log('[RAG] PostgreSQL 处于离线状态，无缝启用 Local Fake RAG 高保真模拟检索...');
      return this.searchLocalFakeDocs(query);
    }

    try {
      const { eq } = require('drizzle-orm');
      // Step 1: Query database rows filtered by businessId (Multi-tenant safe!)
      const rows = await drizzle
        .select({
          id: ragDocuments.id,
          businessId: ragDocuments.businessId,
          chunkText: ragDocuments.chunkText,
          contextualSummary: ragDocuments.contextualSummary,
          embedding: ragDocuments.embedding,
        })
        .from(ragDocuments)
        .where(eq(ragDocuments.businessId, this.businessId));

      const scoredDocs: ScoredRAGDocument[] = [];

      for (const row of rows) {
        let embeddingArray: number[] | null = null;
        if (row.embedding) {
          try {
            embeddingArray = typeof row.embedding === 'string' ? JSON.parse(row.embedding) : row.embedding;
          } catch (e) {
            console.warn('[RAG] Failed to parse row embedding JSON:', e);
          }
        }

        let similarity = 0;
        if (embeddingArray && Array.isArray(embeddingArray) && embeddingArray.length === queryEmbedding.length) {
          // Cosine similarity calculation
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

        // 🧠 混合评分与重排过滤 (Hybrid Score Fusion & Semantic Re-ranking)
        // 结合向量语义距离 (80%) 与核心业务关键词共现奖励 (20%)，防止边缘弱相关文档污染上下文，极大节省 Token 成本
        const queryLower = query.toLowerCase();
        let keywordBonus = 0;
        const hasRefundKeywords = queryLower.includes('退') || queryLower.includes('refund') || queryLower.includes('return') || queryLower.includes('换货');
        const docHasRefundKeywords = row.chunkText.includes('退') || row.chunkText.includes('退款') || row.chunkText.includes('退换货');

        if (hasRefundKeywords && docHasRefundKeywords) {
          keywordBonus = 0.15; // 给予 15% 的高增益相关度加权
        }

        const hybridScore = similarity * 0.8 + keywordBonus * 0.2;

        // 严格断路阀：仅当混合评分 >= 0.40 时予以召回。有效剔除闲聊或不相干提问时的政策垃圾数据干扰
        if (hybridScore >= 0.40) {
          scoredDocs.push({
            id: row.id,
            businessId: row.businessId,
            chunkText: row.chunkText,
            contextualSummary: row.contextualSummary || '',
            similarity: hybridScore,
          });
        }
      }

      // Sort by similarity descending
      const sorted = scoredDocs.sort((a, b) => b.similarity - a.similarity).slice(0, limit);
      console.log(`[RAG] PostgreSQL 物理检索完成，筛选出 ${sorted.length} 个相关 Contextual RAG 切片。`);
      return sorted;
    } catch (dbErr) {
      console.warn('[RAG] PostgreSQL query failed, falling back to Local Fake RAG:', dbErr);
      return this.searchLocalFakeDocs(query);
    }
  }

  // High-fidelity fallback for offline or memory database runs
  private searchLocalFakeDocs(query: string): ScoredRAGDocument[] {
    const fakeData = [
      {
        id: 'fake_rag_1',
        businessId: 'ecommerce',
        chunkText:
          '对于我们电商主站的订单，普通用户享有自签收之日起 7 天无理由退换货权益。退回的商品必须保持吊牌完整、未拆封且不影响二次销售。非质量问题的退货由买家自行承担寄回运费。',
        contextualSummary: '这段切片描述了电商主站（ecommerce）标准 7 天无理由退换货的前提条件与退货运费归属政策。',
      },
      {
        id: 'fake_rag_2',
        businessId: 'nike',
        chunkText:
          'Nike 会员专属福利：支持自订单购买之日起 30 天超长无理由退换货。即使已经拆除吊牌或进行过试穿，只要鞋底无明显磨损，均可享受免费原路退款。退款通过顺丰速运免费寄回。',
        contextualSummary: '这段切片详细说明了 Nike 会员尊享的 30 天无损无理由退货、已拆吊牌退货政策以及顺丰寄回服务。',
      },
      {
        id: 'fake_rag_3',
        businessId: 'adidas',
        chunkText:
          'Adidas 支持签收后 14 天退换货。所有商品必须保留原始包装盒与防伪扣，试穿时请勿弄脏鞋底。退货需要通过官方微信小程序预约快递员上门取件，不支持自行寄送。',
        contextualSummary:
          '这段切片详细规定了 Adidas 的 14 天退换货时效、原始防伪包装要求，以及微信小程序预约取件的硬性物流约束。',
      },
    ];

    // Filter by businessId
    const filtered = fakeData.filter((d) => d.businessId === this.businessId);

    // Simple keyword matching for simulation
    const queryLower = query.toLowerCase();
    const results = filtered.map((d) => {
      let score = 0.5; // Base score
      if (queryLower.includes('退') || queryLower.includes('refund') || queryLower.includes('return')) {
        score += 0.3;
      }
      if (queryLower.includes(this.businessId)) {
        score += 0.15;
      }
      return { ...d, similarity: score };
    });

    return results.sort((a, b) => b.similarity - a.similarity).slice(0, 2);
  }
}
