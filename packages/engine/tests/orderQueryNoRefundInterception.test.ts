import { describe, expect, test } from "bun:test";
import { runAgent } from "../src/graph/buildGraph";
import { triageNode } from "../src/graph/nodes/triage.node";
import type { AgentStateAnnotation } from "../src/graph/state";

describe("Order Query Isolation & Defense Against False Refund Trigger", () => {
  test("Triage node should NOT classify pure order list query as refund intent", async () => {
    const threadId = `test_pure_order_${Date.now()}`;
    const state = {
      threadId,
      input: "我的订单",
      intents: [],
      globalTransitionsCount: 0,
      toolErrorsCount: 0,
      businessConfig: {
        businessId: "ecommerce",
      },
    } as unknown as typeof AgentStateAnnotation.State;

    const result = await triageNode(state);
    expect(result).toBeDefined();
    expect(result.intents).toBeDefined();

    const hasRefundIntent = result.intents?.some((i) => i.intent === "refund");
    expect(hasRefundIntent).toBe(false);
  });

  test('runAgent for "我的订单" should not trigger processRefund or high-risk interception', async () => {
    const threadId = `test_run_order_query_${Date.now()}`;
    const userId = "4c9ce5e9-eb44-4988-b9f4-ec75ec9d8444";
    const jobId = `job_test_no_refund_${Date.now()}`;

    const result = await runAgent(threadId, userId, "我的订单", jobId);
    expect(result.output).not.toContain("processRefund");
    expect(result.output).not.toContain("高危动作");
    expect(result.output).not.toContain("熔断并终止");
    expect(result.output).toContain("ORD-ECOM-889901");
  }, 20000);
});
