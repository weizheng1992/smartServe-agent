import { describe, expect, test } from "bun:test";
import { getDrizzle, lowConfidenceLogs } from "db";
import { eq } from "drizzle-orm";
import { ExemplarHarvestingService } from "../src/graph/nodes/triage/exemplarHarvestingService";
import { ExemplarService } from "../src/graph/nodes/triage/exemplarService";

describe("低置信度日志审核与 Exemplar 样本自愈飞轮测试 (Low-Confidence Flywheel & Exemplar Harvesting)", () => {
  const tenantId = "harvest_test_" + Date.now();

  test("应该能成功将低置信度日志转化为租户 Exemplar 样本并标记为已审核", async () => {
    const drizzle = getDrizzle();
    expect(drizzle).toBeDefined();

    // 1. 模拟生成一条低置信度日志
    const insertedLog = await drizzle!
      .insert(lowConfidenceLogs)
      .values({
        threadId: "thread_harvest_test_" + Date.now(),
        inputText: "你们这个鞋垫可以单买吗",
        candidates: [{ intent: "general_query", confidence: 0.52 }],
        reviewed: false,
      })
      .returning({ id: lowConfidenceLogs.id });

    const logId = insertedLog[0].id;
    expect(logId).toBeDefined();

    // 2. 运营人员审核并沉淀为专属意图
    const harvestResult = await ExemplarHarvestingService.reviewAndHarvestLog({
      logId,
      tenantId,
      confirmedIntentName: "accessory_inquiry",
    });

    expect(harvestResult.success).toBe(true);
    expect(harvestResult.exemplarId).toBeDefined();

    // 3. 验证日志状态已更新为 reviewed = true
    const updatedLogs = await drizzle!
      .select()
      .from(lowConfidenceLogs)
      .where(eq(lowConfidenceLogs.id, logId))
      .limit(1);

    expect(updatedLogs[0].reviewed).toBe(true);

    // 4. 验证新沉淀的样本能够立即在 ExemplarService 中被检索召回
    const recalled = await ExemplarService.searchRelevantExemplars(
      tenantId,
      "你们这个鞋垫可以单买吗",
    );
    expect(recalled.length).toBeGreaterThan(0);
    expect(recalled[0].intentName).toBe("accessory_inquiry");
  });

  test("应该能获取飞轮统计指标", async () => {
    const stats = await ExemplarHarvestingService.getHarvestStats();
    expect(typeof stats.totalPending).toBe("number");
    expect(typeof stats.totalExemplars).toBe("number");
  });
});
