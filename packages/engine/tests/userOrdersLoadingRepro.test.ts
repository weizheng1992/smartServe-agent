import { describe, expect, test } from "bun:test";
import { db } from "db";
import { CardSynthesizer } from "../src/cards/cardSynthesizer";
import { runAgent } from "../src/graph/buildGraph";

describe("Diagnose '我的订单' loading and card rendering issue", () => {
  test("runAgent with '我的订单' should list orders and synthesize order cards", async () => {
    const threadId = `test_thread_orders_${Date.now()}`;
    const userId = "usr_1001";

    // Ensure thread is created
    await db.createThread(threadId, userId, "ecommerce");

    const result = await runAgent(
      threadId,
      userId,
      "我的订单",
      `job_${Date.now()}`,
    );

    console.log("Result output:", result.output);
    console.log("Result taskPlan:", JSON.stringify(result.taskPlan, null, 2));

    expect(result).toBeDefined();
    expect(result.output).toBeDefined();
    expect(result.output.length).toBeGreaterThan(0);

    // Verify subtask executed listUserOrders
    const listSubtask = result.taskPlan?.subtasks?.find(
      (st) =>
        st.id === "step_fast_list_orders" ||
        st.description.toLowerCase().includes("listuserorders"),
    );
    expect(listSubtask).toBeDefined();
    expect(listSubtask?.status).toBe("completed");

    // Verify rich card synthesis works on result
    const synthesizedCards = CardSynthesizer.synthesizeCards({
      taskPlan: result.taskPlan,
    });
    console.log(
      "Synthesized Cards:",
      JSON.stringify(synthesizedCards, null, 2),
    );
    expect(synthesizedCards.length).toBeGreaterThan(0);
    expect(synthesizedCards.some((c) => c.type === "order_card")).toBe(true);
  }, 30000);
});
