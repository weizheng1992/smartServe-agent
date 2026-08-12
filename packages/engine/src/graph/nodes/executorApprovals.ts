import {
  getDrizzle,
  pendingApprovals as dbPendingApprovals,
  db as physicalDb,
} from "db";
import { and, eq } from "drizzle-orm";
import { agentEventEmitter } from "../eventEmitter";
import type { SubTask, TaskPlan } from "../state";

export interface CreateApprovalParams {
  threadId: string;
  userId?: string;
  actionType: string;
  actionPayload: Record<string, unknown>;
  jobId?: string;
  stepToRun: SubTask;
  currentPlan: TaskPlan;
  currentIndex: number;
}

export async function createPendingApprovalTicket({
  threadId,
  userId,
  actionType,
  actionPayload,
  jobId,
  stepToRun,
  currentPlan,
  currentIndex,
}: CreateApprovalParams) {
  try {
    await physicalDb.createThread(
      threadId,
      userId || "83d67d4e-104c-4325-8aa7-10d4389fc725",
    );
  } catch (tErr) {
    console.warn("[Executor Approvals] Thread ensure warning:", tErr);
  }

  let approvalId = crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).substring(2, 15);
  const deadline = new Date(Date.now() + 24 * 60 * 60 * 1000);

  const drizzle = getDrizzle()!;

  const existingApprovals = await drizzle
    .select()
    .from(dbPendingApprovals)
    .where(
      and(
        eq(dbPendingApprovals.threadId, threadId),
        eq(dbPendingApprovals.status, "waiting"),
      ),
    )
    .limit(1);

  if (existingApprovals.length > 0) {
    approvalId = existingApprovals[0].id;
    console.log(
      `[Executor Approvals] 🎯 Thread ${threadId} 已存在挂起中的人工工单 (${approvalId})，无需重复创建！`,
    );
  } else {
    await drizzle.insert(dbPendingApprovals).values({
      id: approvalId,
      threadId,
      actionType,
      actionPayload,
      status: "waiting",
      deadline,
    });
  }

  const updatedStep: SubTask = {
    ...stepToRun,
    status: "completed",
    result: {
      waitingForApproval: true,
      approvalId,
      actionType,
      message:
        actionType === "human_escalation"
          ? "已成功创建人工客服接管工单，请等待客服主管接管回应。"
          : "安全红线拦截：当前属于资金或敏感高危操作，必须等待管理员人工核准放行。",
    },
  };

  const updatedSubtasks = [...currentPlan.subtasks];
  updatedSubtasks[currentIndex] = updatedStep;

  const nextPlan: TaskPlan = {
    ...currentPlan,
    subtasks: updatedSubtasks,
    currentStepIndex: currentIndex + 1,
  };

  if (jobId) {
    agentEventEmitter.emit(`${jobId}:status`, {
      status: "executing",
      node: "executor",
      message:
        actionType === "human_escalation"
          ? `🚨 人工介入接管：已成功建立工单号 [${approvalId}] 的转人工待接管工单，已暂停自动决策流程！`
          : `🛡️ 人工审核拦截：已生成审批工单 [${approvalId}]，暂停自动决策流。`,
      plan: nextPlan,
    });
  }

  return { approvalId, nextPlan };
}
