import { getDrizzle, ragDocuments } from 'db';
import { getEmbeddingModel } from '../llm/callLLMWithRetry';

export interface ScoredRAGDocument {
  id: string;
  businessId: string;
  chunkText: string;
  contextualSummary: string;
  similarity: number;
}

// 🧠 混合检索分词器 (Hybrid Tokenizer): 英文/数字按词拆分，CJK 中文字符按单字（unigram）拆分，完美适配多语言无摩擦全文检索
function tokenize(text: string): string[] {
  const normalized = text.toLowerCase();
  const tokens: string[] = [];
  const regex = /[a-z0-9]+|[一-龥]/g;
  let match = regex.exec(normalized);
  while (match !== null) {
    tokens.push(match[0]);
    match = regex.exec(normalized);
  }
  return tokens;
}

interface DocWithTokens {
  id: string;
  tokens: string[];
}

// 🧮 经典数学 BM25 评分算法实现 (Portable BM25 Engine)
function computeBM25(query: string, docs: DocWithTokens[]): Map<string, number> {
  const queryTokens = tokenize(query);
  const scores = new Map<string, number>();

  if (queryTokens.length === 0 || docs.length === 0) {
    for (const doc of docs) {
      scores.set(doc.id, 0);
    }
    return scores;
  }

  const N = docs.length;
  const k1 = 1.2;
  const b = 0.75;

  let totalLength = 0;
  for (const doc of docs) {
    totalLength += doc.tokens.length;
  }
  const avgdl = totalLength / N || 1;

  const idf = new Map<string, number>();
  for (const token of queryTokens) {
    let n_q = 0;
    for (const doc of docs) {
      if (doc.tokens.includes(token)) {
        n_q++;
      }
    }
    const idfValue = Math.log(Math.max(0.0001, (N - n_q + 0.5) / (n_q + 0.5) + 1));
    idf.set(token, idfValue);
  }

  for (const doc of docs) {
    let score = 0;
    const docLen = doc.tokens.length;
    const termFreqs = new Map<string, number>();
    for (const token of doc.tokens) {
      termFreqs.set(token, (termFreqs.get(token) || 0) + 1);
    }

    for (const token of queryTokens) {
      const f = termFreqs.get(token) || 0;
      if (f > 0) {
        const tokenIDF = idf.get(token) || 0;
        const numerator = f * (k1 + 1);
        const denominator = f + k1 * (1 - b + b * (docLen / avgdl));
        score += tokenIDF * (numerator / denominator);
      }
    }
    scores.set(doc.id, score);
  }

  return scores;
}

interface DocRankItem {
  id: string;
  score: number;
}

// 🔀 倒数排名融合 (RRF - Reciprocal Rank Fusion)
function reciprocalRankFusion(vectorRank: DocRankItem[], bm25Rank: DocRankItem[], k = 60): Map<string, number> {
  const rrfScores = new Map<string, number>();

  const applyRank = (rankList: DocRankItem[]) => {
    rankList.forEach((item, index) => {
      const rank = index + 1;
      const rrfContribution = 1 / (k + rank);
      rrfScores.set(item.id, (rrfScores.get(item.id) || 0) + rrfContribution);
    });
  };

  applyRank(vectorRank);
  applyRank(bm25Rank);

  return rrfScores;
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
            category: 'refund_policy',
          },
          {
            businessId: 'nike',
            chunkText:
              'Nike 会员专属福利：支持自订单购买之日起 30 天超长无理由退换货。即使已经拆除吊牌或进行过试穿，只要鞋底无明显磨损，均可享受免费原路退款。退款通过顺丰速运免费寄回。',
            contextualSummary:
              '这段切片详细说明了 Nike 会员尊享的 30 天无损无理由退货、已拆吊牌退货政策以及顺丰寄回服务。',
            category: 'refund_policy',
          },
          {
            businessId: 'adidas',
            chunkText:
              'Adidas 支持签收后 14 天退换货。所有商品必须保留原始包装盒与防伪扣，试穿时请勿弄脏鞋底。退货需要通过官方微信小程序预约快递员上门取件，不支持自行寄送。',
            contextualSummary:
              '这段切片详细规定了 Adidas 的 14 天退换货时效、原始防伪包装要求，以及微信小程序预约取件的硬性物流约束。',
            category: 'refund_policy',
          },
          {
            businessId: 'nike',
            chunkText:
              'Nike 官方鞋码对照与版型建议：Pegasus 飞马系列跑鞋版型紧凑、足弓包裹感极强。常规脚型建议选择比正装皮鞋大半码；高足弓或宽脚掌用户，强烈建议购买大一码（例如平时穿42码，建议选42.5码或43码），否则易出现脚趾顶红或严重的侧向挤压感。',
            contextualSummary:
              '这段切片详细规定了 Nike 运动鞋（特别是飞马系列跑鞋）的鞋码对照和版型偏小的尺码升级建议。',
            category: 'size_chart',
          },
          {
            businessId: 'adidas',
            chunkText:
              'Adidas 服饰尺码指南：Adidas 户外运动夹克、卫衣与连帽衫整体采用欧美版型剪裁，版型偏向宽松和落肩、Oversized 风格。如果您平时穿着 L 码（适合175cm-180cm），且偏好贴身或标准挺拔版型，建议选择比常规尺码小一号（即 M 码）。',
            category: 'size_chart',
            contextualSummary: '这段切片详细规定了 Adidas 衣服欧版偏宽松落肩的设计特征及建议买小一码的尺码指南。',
          },
          {
            businessId: 'ecommerce',
            chunkText:
              '电商主站常规服饰尺码：通用针织衫、纯棉打底衫尺码为标准中国国标码。M 码适合身高 170cm 左右，L 码适合身高 175cm 左右，XL 码适合身高 180cm 左右。因纯棉材质存在正常 1.5% 的缩水率，建议身高卡在边缘或体型微胖的用户选择大一码。',
            category: 'size_chart',
            contextualSummary: '这段切片规定了电商主站针织衫等标准国标尺码对照，以及考虑纯棉缩水率后的微胖大一码推荐。',
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
            metadata: { category: doc.category, version: '1.0' },
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

      const docEmbeddings = new Map<string, number>();
      const docsWithTokens: DocWithTokens[] = [];

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

        docEmbeddings.set(row.id, similarity);
        docsWithTokens.push({
          id: row.id,
          tokens: tokenize(`${row.contextualSummary || ''} ${row.chunkText}`),
        });
      }

      // Compute standard BM25 Scores
      const bm25Scores = computeBM25(query, docsWithTokens);

      // Build Vector rank list and BM25 rank list for RRF
      const vectorRank: DocRankItem[] = Array.from(docEmbeddings.entries())
        .map(([id, score]) => ({ id, score }))
        .sort((a, b) => b.score - a.score);

      const bm25Rank: DocRankItem[] = Array.from(bm25Scores.entries())
        .filter(([_, score]) => score > 0)
        .map(([id, score]) => ({ id, score }))
        .sort((a, b) => b.score - a.score);

      // Calculate Reciprocal Rank Fusion (RRF) scores
      const rrfScores = reciprocalRankFusion(vectorRank, bm25Rank, 60);

      const scoredDocs: ScoredRAGDocument[] = [];

      for (const row of rows) {
        const similarity = docEmbeddings.get(row.id) || 0;
        const bm25Score = bm25Scores.get(row.id) || 0;

        // 🧠 混合断路阀：对无界的 BM25 进行规范化映射 [0, inf) -> [0, 1)，再以向量相似度 (80%) 与精确关键词 (20%) 混合
        const normalizedBM25 = bm25Score / (bm25Score + 1);
        const hybridScore = similarity * 0.8 + normalizedBM25 * 0.2;

        // 严格断路阀：仅当混合评分 >= 0.40 时予以召回，防止无关噪音垃圾数据污染
        if (hybridScore >= 0.4) {
          scoredDocs.push({
            id: row.id,
            businessId: row.businessId,
            chunkText: row.chunkText,
            contextualSummary: row.contextualSummary || '',
            similarity: hybridScore, // 保持 similarity 为混合得分
          });
        }
      }

      // 🏆 重排：使用 RRF 分数对通过断路阀的文档进行最终精准降序重排
      const sorted = scoredDocs
        .sort((a, b) => {
          const rrfA = rrfScores.get(a.id) || 0;
          const rrfB = rrfScores.get(b.id) || 0;
          return rrfB - rrfA;
        })
        .slice(0, limit);

      console.log(`[RAG] PostgreSQL 物理混合检索检索完成，经 BM25 + RRF 重排筛选出 ${sorted.length} 个相关切片。`);
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

    // Compute high-fidelity BM25 scores on mock data for offline simulation
    const docsWithTokens = filtered.map((d) => ({
      id: d.id,
      tokens: tokenize(`${d.contextualSummary || ''} ${d.chunkText}`),
    }));
    const bm25Scores = computeBM25(query, docsWithTokens);

    const results = filtered.map((d) => {
      const bm25Score = bm25Scores.get(d.id) || 0;
      const normalizedBM25 = bm25Score / (bm25Score + 1);

      // Simulating vector similarity base score:
      // If query has any word matching businessId, increase semantic base score
      let simulatedVectorSimilarity = 0.35; // default base
      const queryLower = query.toLowerCase();
      if (queryLower.includes(this.businessId.toLowerCase())) {
        simulatedVectorSimilarity = 0.65;
      } else if (
        queryLower.includes('退') ||
        queryLower.includes('refund') ||
        queryLower.includes('return') ||
        queryLower.includes('换货')
      ) {
        simulatedVectorSimilarity = 0.55;
      }

      const hybridScore = simulatedVectorSimilarity * 0.8 + normalizedBM25 * 0.2;
      return { ...d, similarity: hybridScore };
    });

    return results
      .filter((r) => r.similarity >= 0.4)
      .sort((a, b) => b.similarity - a.similarity)
      .slice(0, 2);
  }
}
