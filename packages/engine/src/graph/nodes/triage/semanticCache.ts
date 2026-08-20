import { getEmbeddingModel } from '../../../llm/callLLMWithRetry';

export interface CachedQuery {
  query: string;
  reply: string;
  vector: number[];
}

export type SupportedIntent = 'order_status' | 'refund' | 'out_of_scope';

export const DEFAULT_ANCHOR_PHRASES: Readonly<Record<SupportedIntent, readonly string[]>> = {
  order_status: [
    '帮我查询订单物流状态',
    '看看我的订单发货了吗',
    '查询我的快递进度',
    'ORD-98712 的物流信息',
    '这个快递到哪里了',
    '查运单号进度',
    '想看一下我的订单状态',
    '哪些订单可以退货',
    '我可以退货的订单有哪些',
    '查一下支持退款的订单列表',
    '查询我名下的订单',
    '我买了什么东西',
    '查看近期的购物单据',
  ],
  refund: [
    '我想申请退款',
    '帮货品退货退款',
    '不想要了我要退款',
    '退回我的钱',
    '退货流程怎么走',
    '怎么退款',
    '我要退货',
    '帮我把这个订单退了',
  ],
  out_of_scope: [
    '今天天气怎么样',
    '写一段Python代码',
    '帮我订一张电影票',
    '明天会下雨吗',
    '买个东西怎么买',
    '教我做菜',
    '美国总统是谁',
    '附近好吃的餐馆有哪些',
  ],
} as const;

export function cosineSimilarity(vecA: number[], vecB: number[]): number {
  if (vecA.length !== vecB.length) return 0;
  let dotProduct = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < vecA.length; i++) {
    dotProduct += vecA[i] * vecA[i];
    normA += vecA[i] * vecA[i];
    normB += vecB[i] * vecB[i];
  }
  const denom = Math.sqrt(normA) * Math.sqrt(normB);
  return denom === 0 ? 0 : dotProduct / denom;
}

export class SemanticVectorCache {
  private static globalSemanticCache = new Map<string, CachedQuery[]>();
  private static embeddingCache = new Map<string, number[]>();
  private static cachedAnchorVectors: Record<string, number[][]> | null = null;
  private static MAX_TENANT_CACHE_SIZE = 100;
  private static MAX_EMBEDDING_CACHE_SIZE = 500;

  static addQueryToSemanticCache(businessId: string, query: string, reply: string, vector: number[]): void {
    const cleanId = (businessId || 'ecommerce').toLowerCase();
    let list = this.globalSemanticCache.get(cleanId) || [];
    if (list.some((q) => q.query.trim().toLowerCase() === query.trim().toLowerCase())) {
      return;
    }
    list.push({ query, reply, vector });
    if (list.length > this.MAX_TENANT_CACHE_SIZE) {
      list = list.slice(list.length - this.MAX_TENANT_CACHE_SIZE);
    }
    this.globalSemanticCache.set(cleanId, list);
    console.log(`[Semantic Cache] 💾 Added new query to cache for tenant [${cleanId}]: "${query.substring(0, 30)}..."`);
  }

  static findBestSemanticMatch(
    businessId: string,
    userVector: number[],
    minSimilarity = 0.96,
  ): { match: CachedQuery; similarity: number } | null {
    const cleanId = (businessId || 'ecommerce').toLowerCase();
    const cachedItems = this.globalSemanticCache.get(cleanId) || [];
    let bestMatch: CachedQuery | null = null;
    let maxSimilarity = 0;

    for (const cached of cachedItems) {
      const sim = cosineSimilarity(userVector, cached.vector);
      if (sim > maxSimilarity) {
        maxSimilarity = sim;
        bestMatch = cached;
      }
    }

    if (maxSimilarity >= minSimilarity && bestMatch) {
      return { match: bestMatch, similarity: maxSimilarity };
    }
    return null;
  }

  static injectInputEmbedding(text: string, vector: number[]): void {
    if (text && vector && vector.length > 0) {
      this.embeddingCache.set(text.trim().toLowerCase(), vector);
    }
  }

  static async getEmbeddingWithCache(text: string): Promise<number[]> {
    const cleanText = text.trim().toLowerCase();
    if (this.embeddingCache.has(cleanText)) {
      return this.embeddingCache.get(cleanText)!;
    }
    if (this.embeddingCache.size >= this.MAX_EMBEDDING_CACHE_SIZE) {
      const firstKey = this.embeddingCache.keys().next().value;
      if (firstKey) {
        this.embeddingCache.delete(firstKey);
      }
    }
    const embedModel = getEmbeddingModel();
    const vector = await embedModel.embedQuery(cleanText);
    this.embeddingCache.set(cleanText, vector);
    return vector;
  }

  static async getAnchorVectors(): Promise<Record<string, number[][]>> {
    if (this.cachedAnchorVectors) return this.cachedAnchorVectors;

    console.log('[Triage Embedding Cache] 🚀 Initiating reference anchor phrases embedding cache...');
    const embedModel = getEmbeddingModel();

    const orderList = DEFAULT_ANCHOR_PHRASES.order_status;
    const refundList = DEFAULT_ANCHOR_PHRASES.refund;
    const oosList = DEFAULT_ANCHOR_PHRASES.out_of_scope;
    const allTexts = [...orderList, ...refundList, ...oosList];

    const allVectors = await embedModel.embedDocuments(allTexts as string[]);

    const orderVectors = allVectors.slice(0, orderList.length);
    const refundVectors = allVectors.slice(orderList.length, orderList.length + refundList.length);
    const oosVectors = allVectors.slice(orderList.length + refundList.length);

    this.cachedAnchorVectors = {
      order_status: orderVectors,
      refund: refundVectors,
      out_of_scope: oosVectors,
    };

    console.log('[Triage Embedding Cache] ✅ Reference anchor embeddings successfully pre-cached!');
    return this.cachedAnchorVectors;
  }
}
