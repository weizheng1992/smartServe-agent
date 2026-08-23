import { approvalOutboxEvents, getDrizzle } from 'db';
import { and, desc, eq, inArray, lt } from 'drizzle-orm';
import { WorkflowOrchestrator } from '../orchestrator/workflowOrchestrator';

export interface OutboxProcessSummary {
  processedCount: number;
  successCount: number;
  failedCount: number;
}

/**
 * 📮 ApprovalOutboxWorker 事务发件箱对账补偿 Worker (Idempotent Reconciliation Worker)
 * 职责：
 * 1. 周期性扫描未处理完成/网络抖动导致派发失败的 pending / failed 发件箱事件
 * 2. 结合确定性 JobId (job_resume_${approvalId}) 与 Singleflight 机制重放调度
 * 3. 根除“工单已 Approved 但后台未执行”的幽灵审批与双写不一致漏洞
 */
export class ApprovalOutboxWorker {
  private static timer: ReturnType<typeof setInterval> | null = null;
  private static isRunning = false;

  /**
   * 执行一次对账补偿扫描 (Reconciliation Pass)
   * @param olderThanMs 仅补偿生成时间超过该阈值的事件（默认 10 秒，避免与同步 Fast-Path 竞争）
   */
  public static async processPendingEvents(olderThanMs = 10000): Promise<OutboxProcessSummary> {
    const drizzle = getDrizzle();
    if (!drizzle) {
      return { processedCount: 0, successCount: 0, failedCount: 0 };
    }

    const summary: OutboxProcessSummary = {
      processedCount: 0,
      successCount: 0,
      failedCount: 0,
    };

    try {
      // 1. 查询待处理或失败且重试次数 < 5 的 Outbox 事件
      const events = await drizzle
        .select()
        .from(approvalOutboxEvents)
        .where(and(inArray(approvalOutboxEvents.status, ['pending', 'failed']), lt(approvalOutboxEvents.retryCount, 5)))
        .orderBy(desc(approvalOutboxEvents.createdAt))
        .limit(20);

      const cutoffTime = new Date(Date.now() - olderThanMs);
      const eligibleEvents = events.filter((e) => {
        if (olderThanMs === 0) return true;
        const created = e.createdAt ? new Date(e.createdAt) : new Date();
        return created <= cutoffTime;
      });

      summary.processedCount = eligibleEvents.length;

      for (const event of eligibleEvents) {
        // 2. 状态原子迁移为 processing 并递增重试计数
        await drizzle
          .update(approvalOutboxEvents)
          .set({
            status: 'processing',
            retryCount: (event.retryCount || 0) + 1,
            updatedAt: new Date(),
          })
          .where(eq(approvalOutboxEvents.id, event.id));

        const payload = (event.payload as any) || {};
        const deterministicJobId = payload.jobId || `job_resume_${event.approvalId}`;
        const threadId = payload.threadId || event.threadId;
        const userId = payload.userId || '83d67d4e-104c-4325-8aa7-10d4389fc725';
        const message = payload.systemPromptText || 'System: Resume execution.';

        try {
          console.log(
            `[ApprovalOutboxWorker] 🔄 正在重放调度发件箱事件 [ID: ${event.id}, ApprovalID: ${event.approvalId}, JobID: ${deterministicJobId}]...`,
          );

          await WorkflowOrchestrator.dispatchJob({
            jobId: deterministicJobId,
            threadId,
            userId,
            message,
          });

          // 3. 标记为 completed
          await drizzle
            .update(approvalOutboxEvents)
            .set({
              status: 'completed',
              errorMessage: null,
              updatedAt: new Date(),
            })
            .where(eq(approvalOutboxEvents.id, event.id));

          summary.successCount++;
          console.log(`[ApprovalOutboxWorker] ✅ 发件箱事件 [ID: ${event.id}] 补偿恢复成功！`);
        } catch (dispatchErr: any) {
          const errMsg = dispatchErr?.message || String(dispatchErr);
          console.warn(`[ApprovalOutboxWorker] ❌ 发件箱事件 [ID: ${event.id}] 补偿执行失败:`, errMsg);

          await drizzle
            .update(approvalOutboxEvents)
            .set({
              status: 'failed',
              errorMessage: errMsg,
              updatedAt: new Date(),
            })
            .where(eq(approvalOutboxEvents.id, event.id));

          summary.failedCount++;
        }
      }
    } catch (err) {
      console.error('[ApprovalOutboxWorker] 扫描发件箱异常:', err);
    }

    return summary;
  }

  /**
   * 启动后台轮询补偿定时器
   */
  public static startPolling(intervalMs = 5000) {
    if (this.timer) return;
    this.timer = setInterval(async () => {
      if (this.isRunning) return;
      this.isRunning = true;
      try {
        await this.processPendingEvents(10000);
      } finally {
        this.isRunning = false;
      }
    }, intervalMs);
    console.log(`[ApprovalOutboxWorker] 🚀 发件箱补偿 Worker 已就绪 (轮询间隔: ${intervalMs}ms)`);
  }

  /**
   * 停止后台定时器
   */
  public static stopPolling() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
