import { describe, expect, test } from "bun:test";
import { WorkflowOrchestrator } from "../src/orchestrator/workflowOrchestrator";

describe("WorkflowOrchestrator Unit Tests", () => {
  test("Should dispatch job via orchestrator and return dispatch result", async () => {
    const timestamp = Date.now();
    const jobId = `job_test_orch_${timestamp}`;
    const threadId = `test_thread_orch_${timestamp}`;
    const result = await WorkflowOrchestrator.dispatchJob({
      jobId,
      threadId,
      userId: `test_user_orch_${timestamp}`,
      message: "你好，简单询问状态",
    });

    expect(result.jobId).toBe(jobId);
    expect(result.threadId).toBe(threadId);
    expect(result.promise).toBeDefined();

    const execution = WorkflowOrchestrator.getJobExecution(jobId);
    expect(execution).toBeDefined();
  });
});
