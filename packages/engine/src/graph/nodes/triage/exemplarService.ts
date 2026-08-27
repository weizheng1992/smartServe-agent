import { getDrizzle, intentExemplars } from "db";
import { and, eq } from "drizzle-orm";
import { getEmbeddingModel } from "../../../llm/callLLMWithRetry";
import { cosineSimilarity } from "./semanticCache";

export interface ExemplarItem {
  id: string;
  businessId: string;
  intentName: string;
  exampleText: string;
  similarity?: number;
}

export class ExemplarService {
  /**
   * 租户物理隔离的动态 Few-Shot 样本召回
   */
  static async searchRelevantExemplars(
    tenantId: string,
    query: string,
    queryEmbedding?: number[],
    limit = 3,
  ): Promise<ExemplarItem[]> {
    const cleanTenantId = (tenantId || "ecommerce").toLowerCase();
    try {
      const drizzle = getDrizzle();
      if (!drizzle) return [];

      const rows = await drizzle
        .select()
        .from(intentExemplars)
        .where(
          and(
            eq(intentExemplars.businessId, cleanTenantId),
            eq(intentExemplars.isActive, true),
          ),
        )
        .limit(50);

      if (!rows || rows.length === 0) {
        return [];
      }

      let targetVec = queryEmbedding;
      if (!targetVec || targetVec.length === 0) {
        const embeddingModel = getEmbeddingModel();
        targetVec = await embeddingModel.embedQuery(query);
      }

      const scored = rows
        .map((row) => {
          let vecSim = 0;
          if (row.embedding && Array.isArray(row.embedding)) {
            vecSim = cosineSimilarity(
              targetVec as number[],
              row.embedding as number[],
            );
          }
          const textOverlap =
            query.includes(row.exampleText) ||
            row.exampleText.includes(query) ||
            (query.includes("防伪") && row.exampleText.includes("防伪")) ||
            (query.includes("保养") && row.exampleText.includes("保养"))
              ? 0.7
              : 0;
          const finalSim = Math.max(vecSim, textOverlap);
          return {
            id: row.id,
            businessId: row.businessId,
            intentName: row.intentName,
            exampleText: row.exampleText,
            similarity: finalSim,
          };
        })
        .filter((item) => (item.similarity || 0) >= 0.05)
        .sort((a, b) => (b.similarity || 0) - (a.similarity || 0))
        .slice(0, limit);

      return scored;
    } catch (err) {
      console.warn(
        `[ExemplarService] Failed to retrieve exemplars for tenant [${cleanTenantId}]:`,
        err,
      );
      return [];
    }
  }

  /**
   * 格式化 Few-Shot 样本为 Prompt 文本
   */
  static formatExemplarsForPrompt(exemplars: ExemplarItem[]): string {
    if (!exemplars || exemplars.length === 0) return "";
    return exemplars
      .map(
        (ex, idx) =>
          `Sample ${idx + 1}: Query "${ex.exampleText}" -> Intent: "${ex.intentName}"`,
      )
      .join("\n");
  }

  /**
   * 添加或更新租户专属意图样本
   */
  static async addExemplar(
    tenantId: string,
    intentName: string,
    exampleText: string,
    embedding?: number[],
  ): Promise<string> {
    const cleanTenantId = (tenantId || "ecommerce").toLowerCase();
    const drizzle = getDrizzle();
    if (!drizzle) throw new Error("Database connection unavailable");

    let vec = embedding;
    if (!vec || vec.length === 0) {
      const embeddingModel = getEmbeddingModel();
      vec = await embeddingModel.embedQuery(exampleText);
    }

    const inserted = await drizzle
      .insert(intentExemplars)
      .values({
        businessId: cleanTenantId,
        intentName,
        exampleText,
        embedding: vec as any,
        isActive: true,
      })
      .returning({ id: intentExemplars.id });

    return inserted[0]?.id || "unknown";
  }
}
