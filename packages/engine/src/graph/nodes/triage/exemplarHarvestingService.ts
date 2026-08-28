import { getDrizzle, intentExemplars, lowConfidenceLogs } from 'db';
import { and, desc, eq } from 'drizzle-orm';
import { ExemplarService } from './exemplarService';
import { cosineSimilarity } from './semanticCache';

export class ExemplarHarvestingService {
  /**
   * 列出待审核的低置信度日志列表
   */
  static async listPendingReviewLogs(limit = 20) {
    const drizzle = getDrizzle();
    if (!drizzle) return [];

    const rows = await drizzle
      .select()
      .from(lowConfidenceLogs)
      .where(eq(lowConfidenceLogs.reviewed, false))
      .orderBy(desc(lowConfidenceLogs.createdAt))
      .limit(limit);

    return rows;
  }

  /**
   * 审核并沉淀一条低置信度记录为租户 Exemplar 样本 (主动学习自愈飞轮)
   */
  static async reviewAndHarvestLog(options: {
    logId: string;
    tenantId: string;
    confirmedIntentName: string;
    customExampleText?: string;
  }): Promise<{ success: boolean; exemplarId?: string; message: string }> {
    const { logId, tenantId, confirmedIntentName, customExampleText } = options;
    const drizzle = getDrizzle();
    if (!drizzle) throw new Error('Database connection unavailable');

    const cleanTenantId = (tenantId || 'ecommerce').toLowerCase();

    // 1. 获取目标日志记录
    const logRows = await drizzle.select().from(lowConfidenceLogs).where(eq(lowConfidenceLogs.id, logId)).limit(1);

    const logRecord = logRows[0];
    const rawText = customExampleText || logRecord?.inputText;

    if (!rawText) {
      return { success: false, message: 'Log record or input text not found' };
    }

    // 2. 查重保护：避免高相似度（>= 0.95）重复样本冗余堆叠
    const existingExemplars = await ExemplarService.searchRelevantExemplars(cleanTenantId, rawText, undefined, 5);

    let exemplarId = '';
    const duplicate = existingExemplars.find((ex) => (ex.similarity || 0) >= 0.95);

    if (duplicate) {
      // 存在高度重合样本，更新其意图名称即可
      await drizzle
        .update(intentExemplars)
        .set({
          intentName: confirmedIntentName,
          updatedAt: new Date(),
        })
        .where(eq(intentExemplars.id, duplicate.id));
      exemplarId = duplicate.id;
      console.log(
        `[Exemplar Harvesting] 🔄 Updated existing duplicate exemplar [${duplicate.id}] with intent [${confirmedIntentName}]`,
      );
    } else {
      // 创建新样本
      exemplarId = await ExemplarService.addExemplar(cleanTenantId, confirmedIntentName, rawText);
      console.log(`[Exemplar Harvesting] ✨ Harvested new exemplar [${exemplarId}] for tenant [${cleanTenantId}]`);
    }

    // 3. 标记该条日志已被审核
    await drizzle
      .update(lowConfidenceLogs)
      .set({
        reviewed: true,
      })
      .where(eq(lowConfidenceLogs.id, logId));

    return {
      success: true,
      exemplarId,
      message: 'Successfully harvested log into tenant exemplar bank',
    };
  }

  /**
   * 获取样本自愈飞轮统计数据
   */
  static async getHarvestStats(tenantId?: string) {
    const drizzle = getDrizzle();
    if (!drizzle) return { totalPending: 0, totalExemplars: 0 };

    const cleanTenantId = tenantId ? tenantId.toLowerCase() : undefined;

    const pendingQuery = cleanTenantId
      ? drizzle.select().from(lowConfidenceLogs).where(eq(lowConfidenceLogs.reviewed, false))
      : drizzle.select().from(lowConfidenceLogs).where(eq(lowConfidenceLogs.reviewed, false));

    const exemplarQuery = cleanTenantId
      ? drizzle.select().from(intentExemplars).where(eq(intentExemplars.businessId, cleanTenantId))
      : drizzle.select().from(intentExemplars);

    const [pendingRows, exemplarRows] = await Promise.all([pendingQuery, exemplarQuery]);

    return {
      totalPending: pendingRows.length,
      totalExemplars: exemplarRows.length,
    };
  }
}
