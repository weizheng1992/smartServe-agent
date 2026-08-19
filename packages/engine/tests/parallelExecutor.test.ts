import { describe, expect, test } from "bun:test";
import { executorNode } from "../src/graph/nodes/executor.node";
import type { AgentStateAnnotation } from "../src/graph/state";

describe("Parallel Executor Unit Tests", () => {
  test("Executes multiple independent Fast-Path subtasks concurrently in a single step", async () => {
    const threadId = `test_thread_parallel_exec_${Date.now()}`;
    const state: Partial<typeof AgentStateAnnotation.State> = {
      threadId,
      userId: "test_user_parallel",
      input: "查下 ORD-77777 的物流状态，另外查下我名下的全部订单",
      taskPlan: {
        goal: "Query status and list user orders for customer",
        subtasks: [
          {
            id: "step_fast_status_0",
            description: "Call getOrderStatus for order ORD-77777",
            status: "pending",
          },
          {
            id: "step_fast_list_1",
            description: "Call listUserOrders to fetch recent orders",
            status: "pending",
          },
        ],
        currentStepIndex: 0,
      },
      globalTransitionsCount: 0,
    };

    const result = await executorNode(
      state as typeof AgentStateAnnotation.State,
    );

    expect(result).toBeDefined();
    expect(result.taskPlan).toBeDefined();
    // Both subtasks should be executed concurrently in a single executor turn!
    expect(result.taskPlan.subtasks[0].status).toBe("completed");
    expect(result.taskPlan.subtasks[0].result?.toolExecuted).toBe(
      "getOrderStatus",
    );

    expect(result.taskPlan.subtasks[1].status).toBe("completed");
    expect(result.taskPlan.subtasks[1].result?.toolExecuted).toBe(
      "listUserOrders",
    );
  });
});
