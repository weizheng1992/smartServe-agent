import { runAgent } from '../graph/buildGraph';
import { getTemporalClient, isUsingMockTemporal } from '../temporal/client';

export interface DispatchJobOptions {
  jobId: string;
  threadId: string;
  userId: string;
  message: string;
  businessId?: string;
  imageUrls?: string[];
  req?: unknown;
}

export interface DispatchJobResult {
  jobId: string;
  threadId: string;
  userId: string;
  isTemporalMode: boolean;
  promise: Promise<unknown>;
}

export class WorkflowOrchestrator {
  private static agentRuns = new Map<string, Promise<unknown>>();

  /**
   * 🚀 统一分发与调度 Agent 执行 Job (Unified Job Dispatcher)
   */
  public static async dispatchJob(options: DispatchJobOptions): Promise<DispatchJobResult> {
    const { jobId, threadId, userId, message, req } = options;
    const client = await getTemporalClient();
    const isMock = isUsingMockTemporal();

    let promise: Promise<unknown>;

    if (!isMock) {
      console.log(
        `[WorkflowOrchestrator] Connecting to Temporal. Starting workflow ${jobId} on queue 'agent-tasks'...`,
      );
      const workflowPromise = client.workflow.start('agentWorkflow', {
        taskQueue: 'agent-tasks',
        workflowId: jobId,
        args: [threadId, userId, message, options.imageUrls || [], options.businessId],
      });

      const temporalExecPromise = workflowPromise
        .then((handle) => handle.result())
        .catch((err) => {
          console.error(`[WorkflowOrchestrator] Temporal workflow ${jobId} failed:`, err);
          throw err;
        });

      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('TEMPORAL_WORKER_TIMEOUT')), 3500),
      );

      promise = Promise.race([temporalExecPromise, timeoutPromise]).catch(async (err: any) => {
        if (err?.message === 'TEMPORAL_WORKER_TIMEOUT') {
          console.warn(
            `[WorkflowOrchestrator] ⚠️ Temporal 工作流 ${jobId} 等待 Worker 消费超时，自动无缝回退至本地 LangGraph 执行引擎！`,
          );
        } else {
          console.warn(`[WorkflowOrchestrator] ⚠️ Temporal 异常，降级至本地执行:`, err);
        }
        return runAgent(threadId, userId, message, jobId, options.imageUrls, options.businessId);
      });
    } else {
      console.log(
        `[WorkflowOrchestrator] Temporal offline/mock mode. Dispatching to local LangGraph simulator with jobId: ${jobId}...`,
      );
      promise = runAgent(threadId, userId, message, jobId, options.imageUrls, options.businessId);

      if (req && typeof (req as any).waitUntil === 'function') {
        (req as any).waitUntil(promise);
      }
    }

    this.agentRuns.set(jobId, promise);
    if (typeof global !== 'undefined') {
      if (!(global as any).agentRuns) {
        (global as any).agentRuns = new Map();
      }
      (global as any).agentRuns.set(jobId, promise);
    }

    promise.finally(() => {
      this.agentRuns.delete(jobId);
    });

    return {
      jobId,
      threadId,
      userId,
      isTemporalMode: !isMock,
      promise,
    };
  }

  /**
   * 🔍 获取正在运行的 Job 执行 Promise
   */
  public static getJobExecution(jobId: string): Promise<unknown> | undefined {
    return this.agentRuns.get(jobId) || (typeof global !== 'undefined' && (global as any).agentRuns?.get(jobId));
  }
}
