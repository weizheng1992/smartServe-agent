import { randomUUID } from 'node:crypto';
import { db, getDrizzle, pendingApprovals, threads } from 'db';
import { desc, eq } from 'drizzle-orm';
import { WorkflowOrchestrator } from 'engine';
import { redis, useRedis } from 'tools';

export interface ProcessApprovalActionOptions {
  approvalId?: string;
  threadId?: string;
  action?: string;
  rejectionReason?: string;
  humanReply?: string;
  isFinish?: boolean;
}

export interface ProcessApprovalActionResult {
  success?: boolean;
  approvalId?: string;
  jobId?: string;
  threadId?: string;
  status?: string;
  isHumanActive?: boolean;
  approval?: unknown;
  error?: string;
  statusCode?: number;
}

const localLocks = new Set<string>();

export async function listPendingApprovals() {
  const drizzle = getDrizzle()!;
  return drizzle
    .select({
      id: pendingApprovals.id,
      threadId: pendingApprovals.threadId,
      actionType: pendingApprovals.actionType,
      actionPayload: pendingApprovals.actionPayload,
      status: pendingApprovals.status,
      deadline: pendingApprovals.deadline,
      createdAt: pendingApprovals.createdAt,
      businessId: threads.businessId,
    })
    .from(pendingApprovals)
    .innerJoin(threads, eq(pendingApprovals.threadId, threads.id))
    .orderBy(desc(pendingApprovals.createdAt));
}

export async function processApprovalAction(
  options: ProcessApprovalActionOptions,
): Promise<ProcessApprovalActionResult> {
  const { approvalId, threadId, action, rejectionReason, humanReply, isFinish } = options;

  if (action === 'start_human_takeover') {
    const activeThreadId = threadId || 'default_thread';
    await db.createThread(activeThreadId, '83d67d4e-104c-4325-8aa7-10d4389fc725');
    const drizzle = getDrizzle()!;

    const existing = await drizzle
      .select()
      .from(pendingApprovals)
      .where(eq(pendingApprovals.threadId, activeThreadId))
      .orderBy(desc(pendingApprovals.createdAt))
      .limit(1);

    const threadRow = await drizzle
      .select({ businessId: threads.businessId })
      .from(threads)
      .where(eq(threads.id, activeThreadId))
      .limit(1);
    const businessId = threadRow[0]?.businessId || 'ecommerce';

    if (existing[0] && existing[0].status === 'waiting') {
      return {
        success: true,
        approvalId: existing[0].id,
        approval: {
          ...existing[0],
          businessId,
        },
      };
    }

    const newId = randomUUID();
    const deadline = new Date(Date.now() + 1800000);
    const payload = {
      userInput: '客服随时主动接管实时对话',
      reason: '客服主动发起 IM 实时接管',
    };

    await drizzle.insert(pendingApprovals).values({
      id: newId,
      threadId: activeThreadId,
      actionType: 'human_escalation',
      actionPayload: payload,
      status: 'waiting',
      deadline,
    });

    const sysMsgId = randomUUID();

    await db.addMessage({
      id: sysMsgId,
      threadId: activeThreadId,
      role: 'system',
      content: '【系统提示】人工客服已主动接入当前会话，您可以向客服发送消息进行实时沟通。',
      timestamp: new Date().toISOString(),
    });

    const newApproval = {
      id: newId,
      threadId: activeThreadId,
      businessId,
      actionType: 'human_escalation',
      actionPayload: payload,
      status: 'waiting',
      deadline,
      createdAt: new Date().toISOString(),
    };

    return {
      success: true,
      approvalId: newId,
      approval: newApproval,
    };
  }

  if (!approvalId || !action) {
    return {
      error: 'approvalId and action are required',
      statusCode: 400,
    };
  }

  const lockKey = `lock:approval:${approvalId}`;
  let lockAcquired = false;
  let fallbackAcquired = false;

  if (useRedis && redis) {
    try {
      const result = await redis.set(lockKey, 'locked', 'PX', 5000, 'NX');
      lockAcquired = result === 'OK';
    } catch (err) {
      console.warn('[Approval Lock] Redis SETNX failed, falling back to memory lock:', err);
    }
  }

  if (!lockAcquired) {
    if (localLocks.has(lockKey)) {
      console.log(`[Approval Lock] 🎯 锁冲突拦截：工单 ${approvalId} 正在处理中...`);
      return {
        error: '请勿重复提交，审批正在处理中...',
        statusCode: 409,
      };
    }
    localLocks.add(lockKey);
    fallbackAcquired = true;
    setTimeout(() => {
      localLocks.delete(lockKey);
    }, 10000);
  }

  try {
    const drizzle = getDrizzle()!;

    const list = await drizzle.select().from(pendingApprovals).where(eq(pendingApprovals.id, approvalId)).limit(1);

    const record = list[0];
    if (!record) {
      return {
        error: `Approval工单 ${approvalId} 未找到`,
        statusCode: 404,
      };
    }

    if (record.status !== 'waiting') {
      return {
        error: `工单 ${approvalId} 已经处理过，当前状态为: ${record.status}`,
        statusCode: 400,
      };
    }

    if (action === 'human_message' || (action === 'human_reply' && isFinish === false)) {
      if (humanReply && humanReply.trim()) {
        const msgId =
          typeof crypto !== 'undefined' && crypto.randomUUID
            ? crypto.randomUUID()
            : require('node:crypto').randomUUID();
        await db.addMessage({
          id: msgId,
          threadId: record.threadId,
          role: 'assistant',
          content: `[人工客服] ${humanReply.trim()}`,
          timestamp: new Date().toISOString(),
        });
        console.log(`[Human IM Chat] 人工客服回复已实时写入 thread: ${record.threadId}`);
      }
      return {
        success: true,
        isHumanActive: true,
        threadId: record.threadId,
      };
    }

    let nextStatus = 'rejected';
    if (action === 'approve') {
      if (record.actionType === 'human_escalation') {
        nextStatus = 'resolved_by_human';
        const msgId =
          typeof crypto !== 'undefined' && crypto.randomUUID
            ? crypto.randomUUID()
            : require('node:crypto').randomUUID();
        const replyContent =
          (humanReply && humanReply.trim()) || '您好！人工客服专员已接入当前会话为您服务。请问有什么可以帮您？';
        await db.addMessage({
          id: msgId,
          threadId: record.threadId,
          role: 'assistant',
          content: `[人工客服] ${replyContent}`,
          timestamp: new Date().toISOString(),
        });
      } else {
        nextStatus = 'approved';
      }
    } else if (action === 'cancel') {
      nextStatus = 'cancelled';
    } else if (action === 'human_finish' || action === 'human_reply' || record.actionType === 'human_escalation') {
      nextStatus = 'resolved_by_human';

      if (humanReply && humanReply.trim()) {
        const msgId =
          typeof crypto !== 'undefined' && crypto.randomUUID
            ? crypto.randomUUID()
            : require('node:crypto').randomUUID();
        await db.addMessage({
          id: msgId,
          threadId: record.threadId,
          role: 'assistant',
          content: `[人工客服] ${humanReply.trim()}`,
          timestamp: new Date().toISOString(),
        });
      }

      const sysMsgId =
        typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : require('node:crypto').randomUUID();
      await db.addMessage({
        id: sysMsgId,
        threadId: record.threadId,
        role: 'system',
        content: '【系统提示】人工客服服务已结束，已成功为您切回 AI 智能助手。',
        timestamp: new Date().toISOString(),
      });
    }

    const updatedPayload = record.actionPayload
      ? {
          ...(record.actionPayload as Record<string, unknown>),
          rejectionReason: rejectionReason || '',
        }
      : { rejectionReason };

    const finalPayload = {
      ...updatedPayload,
      humanReply: humanReply || '',
    };

    await drizzle
      .update(pendingApprovals)
      .set({
        status: nextStatus,
        actionPayload: finalPayload,
      })
      .where(eq(pendingApprovals.id, approvalId));

    console.log(`[Approval POST] 成功人工处理工单 [ID: ${approvalId}] ➔ 决议为 [${nextStatus}]`);

    if (nextStatus === 'resolved_by_human') {
      return {
        success: true,
        threadId: record.threadId,
        status: nextStatus,
      };
    }

    const jobId = `job_resume_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;

    let systemPromptText = '';
    if (nextStatus === 'approved') {
      systemPromptText = 'System: Human approval granted. Please execute the requested action.';
    } else if (nextStatus === 'cancelled') {
      systemPromptText =
        'System: Human approval cancelled by the user. Please stop the requested action, abort any tool calls for this refund, and explain to the user that the action has been successfully cancelled per their request.';
    } else {
      systemPromptText = `System: Human approval rejected. Reason: ${rejectionReason || 'Not policy compliant'}. Please replan alternative path.`;
    }

    console.log(`[Approval POST] 正在恢复 thread ${record.threadId} 的 Agent 执行流... 新 jobId: ${jobId}`);

    let threadUserId = '83d67d4e-104c-4325-8aa7-10d4389fc725';
    try {
      const dbInstance = getDrizzle()!;
      const threadRows = await dbInstance
        .select({ userId: threads.userId })
        .from(threads)
        .where(eq(threads.id, record.threadId))
        .limit(1);
      if (threadRows[0]?.userId) {
        threadUserId = threadRows[0].userId;
      }
    } catch (err) {
      console.warn('[Approval Route] Failed to fetch thread userId via Drizzle, using record user_id fallback:', err);
    }

    await WorkflowOrchestrator.dispatchJob({
      jobId,
      threadId: record.threadId,
      userId: threadUserId,
      message: systemPromptText,
    });

    return {
      success: true,
      jobId,
      threadId: record.threadId,
      status: nextStatus,
    };
  } finally {
    if (useRedis && redis && lockAcquired) {
      try {
        await redis.del(lockKey);
        console.log(`[Approval Lock] ✅ Redis 分布式锁已物理释放: ${lockKey}`);
      } catch (err) {
        console.warn('[Approval Lock] Redis DEL failed:', err);
      }
    }
    if (fallbackAcquired) {
      localLocks.delete(lockKey);
      console.log(`[Approval Lock] ✅ 内存后备锁已物理释放: ${lockKey}`);
    }
  }
}

export const ApprovalService = {
  listPendingApprovals,
  processApprovalAction,
};
