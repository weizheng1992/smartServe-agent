import { describe, expect, test } from 'bun:test';
import { WorkflowOrchestrator } from '../src/orchestrator/workflowOrchestrator';

describe('WorkflowOrchestrator Unit Tests', () => {
  test('Should dispatch job via orchestrator and return dispatch result', async () => {
    const jobId = `job_test_orch_${Date.now()}`;
    const result = await WorkflowOrchestrator.dispatchJob({
      jobId,
      threadId: 'test_thread_orch_001',
      userId: 'test_user_orch_001',
      message: '你好，简单询问状态',
    });

    expect(result.jobId).toBe(jobId);
    expect(result.threadId).toBe('test_thread_orch_001');
    expect(result.promise).toBeDefined();

    const execution = WorkflowOrchestrator.getJobExecution(jobId);
    expect(execution).toBeDefined();
  });
});
