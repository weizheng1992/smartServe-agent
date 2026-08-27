import { afterAll, beforeAll, describe, expect, it } from "bun:test";
import { ConversationRepository, db, getPgPool } from "db";
import { WorkflowOrchestrator } from "../src";

describe("Merchant User Orders Query Bug Reproduction", () => {
  const pool = getPgPool();
  const testThreadId = `test_thread_zhangwei_${Date.now()}`;
  const testUserId = "CUST-8801";
  const testBusinessId = "aurora";

  beforeAll(async () => {
    // 确保 thread 建立并写入一条消息
    await ConversationRepository.appendMessage({
      threadId: testThreadId,
      businessId: testBusinessId,
      role: "user",
      content: "我的订单",
    });
  });

  it("should resolve user orders for 张伟 (CUST-8801) in aurora merchant", async () => {
    const dispatchRes = await WorkflowOrchestrator.dispatchJob({
      jobId: `job_test_zhangwei_${Date.now()}`,
      threadId: testThreadId,
      userId: testUserId,
      message: "我的订单",
      businessId: testBusinessId,
    });

    const finalState: any = await dispatchRes.promise;
    console.log("[Test Repro Output]:", finalState?.output);
    console.log(
      "[Test Repro Cards]:",
      JSON.stringify(finalState?.cards, null, 2),
    );
    console.log(
      "[Test Repro Subtasks]:",
      JSON.stringify(finalState?.taskPlan?.subtasks, null, 2),
    );

    // 断言不应该报找不到用户上下文或未能获取登录状态
    expect(
      finalState?.taskPlan?.subtasks?.[0]?.result?.output?.error,
    ).toBeUndefined();
    expect(finalState?.output).not.toContain("未能获取到您的账户登录状态");
    expect(finalState?.output).not.toContain("无法直接查询到您");
    expect(finalState?.output).toMatch(/ORD-|冲锋衣|卫衣|订单/i);
    expect(Array.isArray(finalState?.cards)).toBe(true);
    expect(finalState?.cards?.length).toBeGreaterThan(0);
    expect(
      finalState?.cards?.some(
        (c: any) => c.type === "order_card" || c.type === "order_picker",
      ),
    ).toBe(true);
  }, 20000);
});
