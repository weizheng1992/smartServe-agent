import { describe, expect, test } from "bun:test";
import { executorNode } from "../src/graph/nodes/executor.node";

describe("Executor Node Unit Tests", () => {
  test("returns globalTransitionsCount 1 when no subtask exists at currentIndex", async () => {
    const state: any = {
      threadId: "test_thread_empty_subtask",
      taskPlan: {
        goal: "Test empty subtask",
        subtasks: [],
        currentStepIndex: 0,
      },
      globalTransitionsCount: 0,
    };

    const result = await executorNode(state);

    expect(result).toBeDefined();
    expect(result.globalTransitionsCount).toBe(1);
  });

  test("Fast-Path human escalation creates pending approval ticket and suspends", async () => {
    const threadId = `test_thread_exec_escalate_${Date.now()}`;
    const state: any = {
      threadId,
      userId: "test_user_exec",
      input: "我要找人工客服",
      taskPlan: {
        goal: "Escalate to human support",
        subtasks: [
          {
            id: "step_fast_human_escalation",
            description:
              "Trigger human escalation and create pending approval ticket",
            status: "pending",
          },
        ],
        currentStepIndex: 0,
      },
      globalTransitionsCount: 0,
    };

    const result = await executorNode(state);

    expect(result).toBeDefined();
    expect(result.taskPlan).toBeDefined();
    expect(result.taskPlan.subtasks[0].status).toBe("completed");
    expect(result.taskPlan.subtasks[0].result?.waitingForApproval).toBe(true);
    expect(result.taskPlan.subtasks[0].result?.actionType).toBe(
      "human_escalation",
    );

    // Verify DB pending_approvals record
    const { getDrizzle, pendingApprovals } = require("db");
    const { eq } = require("drizzle-orm");
    const drizzle = getDrizzle();
    if (drizzle) {
      const list = await drizzle
        .select()
        .from(pendingApprovals)
        .where(eq(pendingApprovals.threadId, threadId));
      expect(list.length).toBeGreaterThan(0);
      expect(list[0].actionType).toBe("human_escalation");
      expect(list[0].status).toBe("waiting");
    }
  });

  test("Fast-Path getOrderStatus executes physical tool without calling LLM", async () => {
    const threadId = `test_thread_exec_status_${Date.now()}`;
    const state: any = {
      threadId,
      userId: "test_user_exec",
      input: "查询 ORD-98712 物流进度",
      taskPlan: {
        goal: "Query order status",
        subtasks: [
          {
            id: "step_fast_status",
            description: "Call getOrderStatus for order ORD-98712",
            status: "pending",
          },
        ],
        currentStepIndex: 0,
      },
      globalTransitionsCount: 0,
    };

    const result = await executorNode(state);

    expect(result).toBeDefined();
    expect(result.taskPlan).toBeDefined();
    expect(result.taskPlan.subtasks[0].status).toBe("completed");
    expect(result.taskPlan.subtasks[0].result?.toolExecuted).toBe(
      "getOrderStatus",
    );
    expect(result.taskPlan.subtasks[0].result?.output?.orderId).toBe(
      "ORD-98712",
    );
  });

  test("Fast-Path listUserOrders executes tool directly for order listing", async () => {
    const threadId = `test_thread_exec_list_${Date.now()}`;
    const state: any = {
      threadId,
      userId: "test_user_exec",
      input: "查下我名下的全部订单",
      taskPlan: {
        goal: "List user orders",
        subtasks: [
          {
            id: "step_fast_list",
            description: "Call listUserOrders to fetch recent orders",
            status: "pending",
          },
        ],
        currentStepIndex: 0,
      },
      globalTransitionsCount: 0,
    };

    const result = await executorNode(state);

    expect(result).toBeDefined();
    expect(result.taskPlan).toBeDefined();
    expect(result.taskPlan.subtasks[0].status).toBe("completed");
    expect(result.taskPlan.subtasks[0].result?.toolExecuted).toBe(
      "listUserOrders",
    );
  });
});
