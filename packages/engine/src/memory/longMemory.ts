import { getDrizzle, longMemoryFacts } from 'db';
import { getEmbeddingModel, getLLM } from '../llm/callLLMWithRetry';

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

  async extractAndStoreFact(conversationText: string, userQuery?: string): Promise<void> {
    console.log(`[LongMemory] Extracting facts from text for user ${this.userId}`);

    // 🛡️ 启动大模型驱动的异步【专职画像 Agent（Dedicated User Profiler Agent）】
    // 结合历史 SQL 订单购买流水 + 这一轮最新对话，自动提取非结构化尺寸与消费偏好并智能自愈落盘
    if (userQuery) {
      // 异步 Fire-and-forget 运行，绝不阻塞前端实时响应时效
      (async () => {
        try {
          await this.runProfileAudit(userQuery, conversationText);
        } catch (err: any) {
          console.error('[Profiler Agent Error] 专职画像 Agent 执行偏好核查异常:', err.message || err);
        }
      })();
    }

    // 保留原有轻量级正则匹配，做双重容灾保障
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
              confidence: 1.0,
              status: 'approved',
              source: 'regex_fallback',
              createdAt: new Date(),
            });
            console.log(
              `[LongMemory] [Fallback Regex] Extracted and stored fact directly in PostgreSQL [Status: approved]: "${factText}"`,
            );
          } catch (err) {
            console.warn('[LongMemory] Drizzle insertion bypassed due to offline/failed DB.');
          }
        }
      }
    }
  }

  /**
   * 🕵️ 专职画像 Agent (Dedicated Profiler Agent) 核心研判器
   * 结合：SQL 结构化订单历史 + 本轮最新非结构化聊天上下文
   */
  private async runProfileAudit(userQuery: string, assistantResponse: string): Promise<void> {
    console.log(`[Profiler Agent] 🕵️ 启动用户 ${this.userId} 的多模态消费画像提取...`);

    const { db: physicalDb } = require('db');
    let pastOrders: any[] = [];

    // 1. [结构化数据装配 (SQL)]：实时拉取该用户在 PostgreSQL 中的最近购买明细
    try {
      const orderRes = await physicalDb.execute(
        `
        SELECT o.order_id AS "orderId", o.status, p.name AS "productName", o.total_amount AS "totalAmount"
        FROM orders o
        LEFT JOIN order_items oi ON o.order_id = oi.order_id
        LEFT JOIN products p ON oi.product_id = p.id
        WHERE o.user_id = $1 LIMIT 5
      `,
        [this.userId],
      );
      pastOrders = orderRes.rows || [];
    } catch (sqlErr) {
      console.warn('[Profiler Agent] Failed to fetch SQL transaction stream for audit:', sqlErr);
    }

    // 2. [画像大模型研判]：注入多模态画像提取 Prompts，输出极致规整的 JSONB 标签
    const llm = getLLM();
    const systemPrompt = `
你是一位世界级的消费者行为学家与尺码换算专家。你的职责是通过分析【用户最新的对话细节】与【历史购买流水】，提炼出符合该用户特征的个性化消费画像标签并进行置信度（Confidence）评估。

[CRITICAL INSTRUCTIONS]:
请不要生成任何解释性废话。你必须只输出一个合规的 JSON 对象，包含以下字段：
{
  "hasNewPreference": boolean, // 本轮对话中是否展现出任何新的、值得记录的尺码偏好、颜色偏好或避雷标签？
  "extractedFacts": [
    {
      "fact": string, // 非结构化偏好事实描述。例如: "用户上衣尺码为 L 码", "用户鞋子尺码为 42.5 码"
      "confidence": number, // 置信度评分 (0.0 - 1.0)。如果用户明确口头告知，置信度设为 0.90 - 1.00；如果通过购买历史推断，设为 0.70 - 0.85；如果是模糊语境推断，设为 0.50 - 0.69
      "source": string // 画像数据来源描述。例如 "user_direct_statement" (用户直接表述), "purchase_history_inference" (购买历史推导), "contextual_inference" (语境模糊推导)
    }
  ]
}

注意：如果用户在聊天中提到了“长胖了衣服得穿XL”或“耐克鞋42有些挤脚下次买42.5”，或者通过 SQL 历史单据发现他大量购买了黑色运动卫衣，请敏锐地提取这些关键消费特征！
不要胡编乱造，仅提炼用户明确流露或被历史购买记录证实的偏好标签。
`;

    const auditPrompt = `
${systemPrompt}

[INPUT CONTEXT]:
1. 🛍️ 用户历史购买流水 (SQL Transaction Stream):
${JSON.stringify(pastOrders, null, 2)}

2. 💬 本轮最新聊天交互 (Conversational Context):
- Customer: "${userQuery}"
- Assistant: "${assistantResponse}"

请进行画像分析并返回结果 JSON：
`;

    try {
      const response = await llm.invoke(auditPrompt);
      const content = typeof response === 'string' ? response : (response as any).content || '';

      const cleanJson = content
        .trim()
        .replace(/^```json\s*/, '')
        .replace(/```$/, '')
        .trim();

      const auditResult = JSON.parse(cleanJson);

      if (!auditResult.hasNewPreference || !auditResult.extractedFacts || auditResult.extractedFacts.length === 0) {
        console.log('[Profiler Agent] 🍃 画像审计完成：本轮会话未检测到新的偏好特征变动。');
        return;
      }

      console.log(
        `[Profiler Agent] 🎯 画像专家捕捉到 ${auditResult.extractedFacts.length} 条全新消费偏好！开始向量化归档 RAG 长期记忆...`,
      );

      const drizzle = getDrizzle();
      if (!drizzle) return;

      // 3. [非结构化偏好 RAG 落盘]：计算向量嵌入并同步落盘
      const embeddingModel = getEmbeddingModel();
      for (const item of auditResult.extractedFacts) {
        try {
          const factText = typeof item === 'string' ? item : item.fact;
          const confidence = typeof item === 'string' ? 1.0 : item.confidence || 1.0;
          const source = typeof item === 'string' ? 'agent_audit_legacy' : item.source || 'agent_audit';

          // 🧠 画像置信度过滤硬性红线（High/Mid Threshold Routing）：
          // 1. 置信度 >= 0.85 的高级画像，直接赋予 'approved' 状态秒级投入对话生产使用。
          // 2. 置信度在 [0.60, 0.85) 的中级画像，赋予 'pending' 状态，存入数据库但对前台 Agent 隐身，等待人工审批核签。
          // 3. 置信度 < 0.60 的低置信度画像，直接丢弃，拦截模型幻觉。
          if (confidence < 0.60) {
            console.log(`[Profiler Agent Filter] 🚫 Fact low confidence (${confidence.toFixed(2)} < 0.60). Discarded: "${factText}"`);
            continue;
          }

          const status = confidence >= 0.85 ? 'approved' : 'pending';
          console.log(`[Profiler Agent Routing] 🎯 Fact "${factText}" rated ${confidence.toFixed(2)} confidence ➔ Routed to status [${status}]`);

          const embedding = await embeddingModel.embedQuery(factText);
          const serializedEmbedding = JSON.stringify(embedding);

          await drizzle.insert(longMemoryFacts).values({
            userId: this.userId,
            fact: factText,
            embedding: serializedEmbedding,
            type: 'preference',
            confidence: confidence,
            status: status,
            source: source,
            createdAt: new Date(),
          });
          console.log(`[Profiler Agent] 偏好 RAG 事实成功写入 longMemoryFacts [Status: ${status}]: "${factText}"`);
        } catch (ragErr) {
          console.warn('[Profiler Agent] Failed to vectorise and store extracted fact:', ragErr);
        }
      }

      console.log(`[Profiler Agent] ✅ 用户 ${this.userId} 的消费特征同步更新成功！`);
    } catch (err: any) {
      console.error('[Profiler Agent Error] 画像 Agent 提取偏好发生异常:', err.message || err);
    }
  }

  async searchRelevantFacts(query: string, precomputedEmbedding?: number[]): Promise<LongMemoryFact[]> {
    console.log(`[LongMemory] Searching relevant facts for user ${this.userId} using query: ${query}`);

    let queryEmbedding = precomputedEmbedding;
    if (!queryEmbedding || queryEmbedding.length === 0) {
      const embeddingModel = getEmbeddingModel();
      queryEmbedding = await embeddingModel.embedQuery(query);
    }

    const dbInstance = getDrizzle();
    if (dbInstance) {
      try {
        const { eq, and } = require('drizzle-orm');
        // Retrieve all facts for the user and perform in-memory cosine similarity calculation in TS.
        // 🔒 Only recall approved facts to prevent pending/rejected data leakage into the active prompt.
        const allFacts = await dbInstance
          .select({
            id: longMemoryFacts.id,
            fact: longMemoryFacts.fact,
            type: longMemoryFacts.type,
            embedding: longMemoryFacts.embedding,
            createdAt: longMemoryFacts.createdAt,
          })
          .from(longMemoryFacts)
          .where(
            and(
              eq(longMemoryFacts.userId, this.userId),
              eq(longMemoryFacts.status, 'approved')
            )
          );

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
