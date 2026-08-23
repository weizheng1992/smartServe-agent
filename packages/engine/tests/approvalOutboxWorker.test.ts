import { randomUUID } from "node:crypto";
import { describe, expect, it } from "bun:test";
import {
  approvalOutboxEvents,
  db,
  getDrizzle,
  pendingApprovals as dbPendingApprovals,
} from "db";
import { eq } from "drizzle-orm";
import { ApprovalGatekeeper } from "../src/approval/approvalGatekeeper";
import { ApprovalOutboxWorker } from "../src/approval/approvalOutboxWorker";
import { WorkflowOrchestrator } from "../src/orchestrator/workflowOrchestrator";

describe("📮 Transactional Outbox & Deterministic Resumption Suite (TDD)", () => {
  it("Fast-Path 正常流：审批通过后原子写入 Outbox 事件并通过确定性 Job ID 成功派发", async () => {
    const threadId = `test_outbox_thread_${Date.now()}`;
    const approvalId = randomUUID();
    const drizzle = getDrizzle()!;

    // 1. 准备初始 waiting 审批工单
    await db.createThread(threadId, "user_outbox_001", "ecommerce");
    await drizzle.insert(dbPendingApprovals).values({
      id: approvalId,
      threadId,
      actionType: "processRefund",
      actionPayload: {
        orderId: "ORD-OUTBOX-001",
        refundAmount: 500,
      },
      status: "waiting",
      deadline: new Date(Date.now() + 86400000),
    });

    // 2. 审批通过
    const res = await ApprovalGatekeeper.processApprovalAction({
      approvalId,
      threadId,
      action: "approve",
    });

    expect(res.success).toBe(true);
    expect(res.status).toBe("approved");
    expect(res.jobId).toBe(`job_resume_${approvalId}`);

    // 3. 验证 Outbox 表状态为 completed
    const outboxRows = await drizzle
      .select()
      .from(approvalOutboxEvents)
      .where(eq(approvalOutboxEvents.approvalId, approvalId));

    expect(outboxRows.length).toBe(1);
    expect(outboxRows[0].status).toBe("completed");
    expect(outboxRows[0].eventType).toBe("resume_execution");
    const payload = outboxRows[0].payload as any;
    expect(payload.jobId).toBe(`job_resume_${approvalId}`);
  });

  it("💥 故障注入与对账补偿：派发阶段网络抛错崩溃，对账 Worker 能够自动捕获并成功恢复任务", async () => {
    const threadId = `test_fault_thread_${Date.now()}`;
    const approvalId = randomUUID();
    const drizzle = getDrizzle()!;

    // 1. 准备初始 waiting 审批工单
    await db.createThread(threadId, "user_outbox_002", "ecommerce");
    await drizzle.insert(dbPendingApprovals).values({
      id: approvalId,
      threadId,
      actionType: "processRefund",
      actionPayload: {
        orderId: "ORD-OUTBOX-002",
        refundAmount: 1200,
      },
      status: "waiting",
      deadline: new Date(Date.now() + 86400000),
    });

    // 2. 注入故障：劫持 WorkflowOrchestrator.dispatchJob 抛出网络瞬断异常
    const originalDispatch = WorkflowOrchestrator.dispatchJob;
    let faultInjected = true;
    (WorkflowOrchestrator as any).dispatchJob = async (opts: any) => {
      if (faultInjected) {
        throw new Error(
          "Network timeout during Temporal/simulator dispatch (Simulated Crash)",
        );
      }
      return originalDispatch.call(WorkflowOrchestrator, opts);
    };

    try {
      // 3. 触发审批决议（此时 Fast-Path 调度失败，但事务保证工单与 Outbox 事件已原子提交）
      const res = await ApprovalGatekeeper.processApprovalAction({
        approvalId,
        threadId,
        action: "approve",
      });

      expect(res.success).toBe(true);
      expect(res.status).toBe("approved");

      // 4. 验证数据库中 Outbox 处于 pending 状态，且记录了错误信息
      const outboxPending = await drizzle
        .select()
        .from(approvalOutboxEvents)
        .where(eq(approvalOutboxEvents.approvalId, approvalId));

      expect(outboxPending.length).toBe(1);
      expect(outboxPending[0].status).toBe("pending");
      expect(outboxPending[0].errorMessage).toContain("Simulated Crash");

      // 5. 恢复网络环境并触发对账 Worker 补偿
      faultInjected = false;
      const summary = await ApprovalOutboxWorker.processPendingEvents(0);

      expect(summary.processedCount).toBeGreaterThanOrEqual(1);
      expect(summary.successCount).toBeGreaterThanOrEqual(1);

      // 6. 验证 Outbox 状态最终成功迁移为 completed
      const outboxResolved = await drizzle
        .select()
        .from(approvalOutboxEvents)
        .where(eq(approvalOutboxEvents.approvalId, approvalId));

      expect(outboxResolved[0].status).toBe("completed");
      expect(outboxResolved[0].retryCount).toBeGreaterThanOrEqual(1);

      // 7. 幂等性验证：再次运行补偿 Worker，不应再有待处理事件
      const summaryIdempotent =
        await ApprovalOutboxWorker.processPendingEvents(0);
      expect(summaryIdempotent.processedCount).toBe(0);
    } finally {
      // 还原 dispatchJob
      (WorkflowOrchestrator as any).dispatchJob = originalDispatch;
    }
  });
});
