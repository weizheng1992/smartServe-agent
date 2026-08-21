import { describe, expect, test } from "bun:test";
import { db } from "db";
import { WorkflowOrchestrator } from "../src/orchestrator/workflowOrchestrator";
import { getTemporalClient, isUsingMockTemporal } from "../src/temporal/client";

describe("Temporal & Orchestrator Dispatch for '我的订单'", () => {
  test("dispatchJob with '我的订单' should complete without hanging", async () => {
    const threadId = `test_thread_orch_${Date.now()}`;
    const userId = "usr_1001";
    const jobId = `job_orch_test_${Date.now()}`;

    await db.createThread(threadId, userId);

    const client = await getTemporalClient();
    const isMock = isUsingMockTemporal();
    console.log("isMock Temporal:", isMock);

    const dispatchResult = await WorkflowOrchestrator.dispatchJob({
      jobId,
      threadId,
      userId,
      message: "我的订单",
    });

    console.log("dispatchResult:", {
      jobId: dispatchResult.jobId,
      isTemporalMode: dispatchResult.isTemporalMode,
    });

    const result = await Promise.race([
      dispatchResult.promise,
      new Promise((_, reject) =>
        setTimeout(
          () => reject(new Error("dispatchJob TIMEOUT after 30s")),
          28000,
        ),
      ),
    ]);

    console.log("Dispatched job completed result:", result);
    expect(result).toBeDefined();
  }, 30000);
});
