import { randomUUID } from "node:crypto";
import {
  approvalOutboxEvents,
  db,
  pendingApprovals as dbPendingApprovals,
  getDrizzle,
  threads,
  users,
} from "db";
import { and, desc, eq, sql } from "drizzle-orm";
import { redis, useRedis } from "tools";
import type { PendingApprovalRecord } from "types";
import { agentEventEmitter } from "../graph/eventEmitter";
import type { SubTask, TaskPlan } from "../graph/state";
import { WorkflowOrchestrator } from "../orchestrator/workflowOrchestrator";

export interface ApprovalPolicyResult {
  state:
    | "approved"
    | "waiting"
    | "rejected"
    | "cancelled"
    | "expired"
    | "double_refund_blocked";
  approvalId?: string;
  message?: string;
  error?: string;
  rejectionReason?: string;
  isApproved?: boolean;
}

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

const localLocks = new Set<string>();

/**
 * 🛡️ ApprovalGatekeeper 深模块门面 (Deep Domain Subsystem)
 * 统一封装:
 * 1. 资金/操作安全红线检测 (Double-refund check, auto-approval limit, address policy)
 * 2. 挂起工单生命周期与超时熔断 (Ticket creation, waiting state, deadline expiration)
 * 3. 分布式 Redis SETNX 互斥锁与内存锁保护
 * 4. 决议状态机迁移 (approved / rejected / cancelled / resolved_by_human)
 * 5. 执行流断点自动唤醒与续跑分发 (WorkflowOrchestrator resume prompt dispatch)
 */
export class ApprovalGatekeeper {
  /**
   * 🛡️ 校验重复退款防护 (Double-Refund Prevention)
   */
  public static async checkDoubleRefund(
    orderId: string,
  ): Promise<{ isDoubleRefund: boolean; status?: string }> {
    try {
      const oRes = await db.execute(
        'SELECT total_amount AS "totalAmount", status FROM orders WHERE order_id = $1',
        [orderId],
      );
      if (oRes?.rows?.[0]) {
        const row = oRes.rows[0] as any;
        if (row.status === "refunded") {
          return { isDoubleRefund: true, status: row.status };
        }
        return { isDoubleRefund: false, status: row.status };
      }
    } catch (err) {
      console.warn("[ApprovalGatekeeper] Double refund check DB error:", err);
    }
    return { isDoubleRefund: false };
  }

  /**
   * 🪙 评估退款免签额度 (Refund Auto-Approval Threshold Evaluation)
   */
  public static async evaluateRefundAutoApproval(
    orderId?: string,
    refundAmountArg?: any,
    autoApprovalLimit = 100,
  ): Promise<{ shouldAutoApprove: boolean; groundedAmount: number }> {
    let refundAmount = 999999.99;
    const amountStr = refundAmountArg ? String(refundAmountArg) : undefined;

    if (amountStr) {
      refundAmount =
        Number.parseFloat(amountStr.replace(/[^0-9.]/g, "")) || 999999.99;
    }

    if (orderId && !amountStr) {
      try {
        const oRes = await db.execute(
          'SELECT total_amount AS "totalAmount" FROM orders WHERE order_id = $1',
          [orderId],
        );
        if (oRes?.rows?.[0]) {
          const dbAmt = (oRes.rows[0] as any).totalAmount;
          if (dbAmt) {
            refundAmount =
              Number.parseFloat(String(dbAmt).replace(/[^0-9.]/g, "")) ||
              999999.99;
          }
        }
      } catch (err) {
        console.warn("[ApprovalGatekeeper] Grounding order amount error:", err);
      }
    }

    return {
      shouldAutoApprove: refundAmount <= autoApprovalLimit,
      groundedAmount: refundAmount,
    };
  }

  /**
   * 🚚 评估高价值订单地址变更红线 (High-Value Address Change Policy)
   */
  public static async evaluateAddressChangePolicy(
    orderId?: string,
  ): Promise<{ isHighValue: boolean; totalAmount: number }> {
    if (!orderId) return { isHighValue: false, totalAmount: 0 };

    try {
      const oRes = await db.execute(
        'SELECT total_amount AS "totalAmount", status FROM orders WHERE order_id = $1',
        [orderId],
      );
      if (oRes?.rows?.[0]) {
        const row = oRes.rows[0] as any;
        const totalAmount = Number(row.totalAmount || row.total_amount || 0);
        const status = row.status || "";

        if (
          status !== "shipped" &&
          status !== "delivered" &&
          totalAmount > 100.0
        ) {
          return { isHighValue: true, totalAmount };
        }
      }
    } catch (err) {
      console.warn("[ApprovalGatekeeper] Address policy DB error:", err);
    }

    return { isHighValue: false, totalAmount: 0 };
  }

  /**
   * 🔍 通过工单 ID 查询审批详情 (纯领域门面)
   */
  public static async findApprovalById(
    approvalId: string,
  ): Promise<PendingApprovalRecord | null> {
    try {
      const res = await db.execute(
        'SELECT id, thread_id AS "threadId", action_type AS "actionType", action_payload AS "actionPayload", status, deadline, created_at AS "createdAt" FROM pending_approvals WHERE id = $1 LIMIT 1',
        [approvalId],
      );
      if (res.rows?.[0]) {
        const row = res.rows[0] as any;
        const parsedPayload =
          typeof row.actionPayload === "string"
            ? JSON.parse(row.actionPayload)
            : row.actionPayload;
        return {
          id: row.id,
          threadId: row.threadId,
          actionType: row.actionType,
          actionPayload: parsedPayload,
          status: row.status,
          reason: parsedPayload?.rejectionReason || parsedPayload?.reason,
          deadline: row.deadline ? new Date(row.deadline) : undefined,
          createdAt: row.createdAt ? new Date(row.createdAt) : undefined,
        };
      }
    } catch (err) {
      console.warn("[ApprovalGatekeeper] findApprovalById DB error:", err);
    }
    return null;
  }

  /**
   * 🔍 查询会话最新的待审核/已审核工单记录
   */
  public static async findLatestApprovalByThreadId(
    threadId: string,
  ): Promise<PendingApprovalRecord | null> {
    try {
      const res = await db.execute(
        'SELECT id, thread_id AS "threadId", action_type AS "actionType", action_payload AS "actionPayload", status, deadline, created_at AS "createdAt" FROM pending_approvals WHERE thread_id = $1 ORDER BY created_at DESC LIMIT 1',
        [threadId],
      );
      if (res.rows?.[0]) {
        const row = res.rows[0] as any;
        const parsedPayload =
          typeof row.actionPayload === "string"
            ? JSON.parse(row.actionPayload)
            : row.actionPayload;
        return {
          id: row.id,
          threadId: row.threadId,
          actionType: row.actionType,
          actionPayload: parsedPayload,
          status: row.status,
          reason: parsedPayload?.rejectionReason || parsedPayload?.reason,
          deadline: row.deadline ? new Date(row.deadline) : undefined,
          createdAt: row.createdAt ? new Date(row.createdAt) : undefined,
        };
      }
    } catch (err) {
      console.warn(
        "[ApprovalGatekeeper] findLatestApprovalByThreadId DB error:",
        err,
      );
    }
    return null;
  }

  /**
   * ⏰ 评估执行中待挂起/挂起中工单的状态迁移与超时解挂
   */
  public static async evaluatePendingApprovalState(opts: {
    threadId: string;
    toolName: string;
    args: Record<string, unknown>;
    stepDescription: string;
    stepIndex: number;
    existingApprovalId?: string;
  }): Promise<ApprovalPolicyResult> {
    const drizzle = getDrizzle();
    if (!drizzle) {
      return { state: "approved", isApproved: false };
    }

    let latestApproval: any = null;

    if (opts.existingApprovalId) {
      const approvalsList = await drizzle
        .select()
        .from(dbPendingApprovals)
        .where(eq(dbPendingApprovals.id, opts.existingApprovalId))
        .limit(1);
      latestApproval = approvalsList[0] || null;
    }

    if (!latestApproval) {
      const approvalsList = await drizzle
        .select()
        .from(dbPendingApprovals)
        .where(eq(dbPendingApprovals.threadId, opts.threadId))
        .orderBy(desc(dbPendingApprovals.createdAt));

      latestApproval =
        approvalsList.find((app: any) => {
          const actionPayload = (app.actionPayload as any) || {};
          const payloadArgs = actionPayload.args || {};
          const currentArgs = opts.args || {};

          if (app.actionType !== opts.toolName) return false;

          if (currentArgs.orderId && payloadArgs.orderId) {
            return (
              String(currentArgs.orderId).trim().toLowerCase() ===
              String(payloadArgs.orderId).trim().toLowerCase()
            );
          }

          return JSON.stringify(payloadArgs) === JSON.stringify(currentArgs);
        }) || null;
    }

    // 1. 超时解挂检测 (Deadline Check)
    if (latestApproval && latestApproval.status === "waiting") {
      const now = new Date();
      const deadlineDate = latestApproval.deadline
        ? new Date(latestApproval.deadline)
        : null;
      const isExpired = deadlineDate && now > deadlineDate;

      if (isExpired) {
        await drizzle
          .update(dbPendingApprovals)
          .set({ status: "expired" })
          .where(eq(dbPendingApprovals.id, latestApproval.id));

        const isRefund = opts.toolName === "processRefund";
        const dateStr = deadlineDate ? deadlineDate.toLocaleString() : "未知";
        return {
          state: "expired",
          approvalId: latestApproval.id,
          error: isRefund
            ? "人工审批已超时。大额资金退款未获得授权，暂未办理。"
            : "人工审批已超时。高价值订单地址修改申请未获得授权，暂未办理。",
          message: isRefund
            ? `⚠️ 安全核发超时：人工审核申请 (ID: ${latestApproval.id}) 已超过截止审批时间 (${dateStr}) 仍未获得核准，系统已自动实施超时安全解挂熔断。退款暂未执行，请联系客服转人工处理。`
            : `⚠️ 安全核发超时：订单地址修改人工审核申请 (ID: ${latestApproval.id}) 已超过截止审批时间 (${dateStr}) 仍未获得授权，系统已自动实施超时安全解挂熔断。修改暂未生效。`,
        };
      }
    }

    // 2. 无历史工单，创建新工单挂起
    if (!latestApproval) {
      const newApprovalId = randomUUID();
      const deadline = new Date(Date.now() + 24 * 3600 * 1000);

      await drizzle.insert(dbPendingApprovals).values({
        id: newApprovalId,
        threadId: opts.threadId,
        actionType: opts.toolName,
        actionPayload: {
          description: opts.stepDescription,
          args: opts.args,
          stepIndex: opts.stepIndex,
        },
        status: "waiting",
        deadline,
      });

      return {
        state: "waiting",
        approvalId: newApprovalId,
        message:
          opts.toolName === "processRefund"
            ? `⚠️ 安全拦截：系统检测到敏感支付操作 [退款金额: ${opts.args?.refundAmount || "100% 原路退回"}]。已物理拦截并自动生成人工审批工单 (ID: ${newApprovalId})。后台执行处于无阻塞安全挂起中，请管理员点击页面右上角【人工授权模拟面板】进行核发或驳回。`
            : `⚠️ 安全拦截：检测到高价值订单修改敏感操作 [申请更新配送地址为: ${opts.args?.newAddress || "新地址"}]。已物理拦截并自动生成人工审批工单 (ID: ${newApprovalId})。后台执行处于无阻塞安全挂起中，请管理员点击页面右上角【人工授权模拟面板】进行核发或驳回。`,
      };
    }

    // 3. 状态已为 waiting
    if (latestApproval.status === "waiting") {
      return {
        state: "waiting",
        approvalId: latestApproval.id,
        message: "审批工单审核中，任务保持挂起。",
      };
    }

    // 4. 被用户取消
    if (latestApproval.status === "cancelled") {
      return {
        state: "cancelled",
        approvalId: latestApproval.id,
        error: "用户已取消此项操作。",
        message: "⚠️ 您已主动取消了此笔审批。相关操作已被物理终止。",
      };
    }

    // 5. 被管理员驳回
    if (latestApproval.status === "rejected") {
      const payload = (latestApproval.actionPayload as any) || {};
      const reason = payload.rejectionReason || "申请不符合政策要求。";
      return {
        state: "rejected",
        approvalId: latestApproval.id,
        rejectionReason: reason,
        message: `❌ 人工审核拒绝：管理员驳回了本次申请，理由: [${reason}]。决策引擎即将启动回溯重规划。`,
      };
    }

    // 6. 已核准放行
    return {
      state: "approved",
      approvalId: latestApproval.id,
      isApproved: true,
    };
  }

  /**
   * 📋 查询工单清单（联合 threads 及 users 穿透客户身份，支持 SQL 级租户与状态下推过滤）
   */
  public static async listPendingApprovals(filter?: {
    tenantId?: string;
    businessId?: string;
    status?: string;
  }): Promise<PendingApprovalRecord[]> {
    const drizzle = getDrizzle()!;
    const conditions: any[] = [];
    const targetTenant = (filter?.tenantId || filter?.businessId || "")
      .toLowerCase()
      .trim();

    if (targetTenant && targetTenant !== "all" && targetTenant !== "admin") {
      conditions.push(eq(threads.businessId, targetTenant));
    }

    if (filter?.status && filter.status !== "all") {
      conditions.push(eq(dbPendingApprovals.status, filter.status));
    }

    const baseQuery = drizzle
      .select({
        id: dbPendingApprovals.id,
        threadId: dbPendingApprovals.threadId,
        userId: threads.userId,
        userEmail: users.email,
        actionType: dbPendingApprovals.actionType,
        actionPayload: dbPendingApprovals.actionPayload,
        status: dbPendingApprovals.status,
        deadline: dbPendingApprovals.deadline,
        createdAt: dbPendingApprovals.createdAt,
        businessId: threads.businessId,
      })
      .from(dbPendingApprovals)
      .leftJoin(threads, eq(dbPendingApprovals.threadId, threads.id))
      .leftJoin(users, sql`${threads.userId} = ${users.id}::text`);

    const rows =
      conditions.length > 0
        ? await baseQuery
            .where(and(...conditions))
            .orderBy(desc(dbPendingApprovals.createdAt))
        : await baseQuery.orderBy(desc(dbPendingApprovals.createdAt));

    return rows as PendingApprovalRecord[];
  }

  /**
   * 🚀 创建待核准工单（供 Executor 节点调度）
   */
  public static async createPendingApprovalTicket({
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
      await db.createThread(
        threadId,
        userId || "83d67d4e-104c-4325-8aa7-10d4389fc725",
      );
    } catch (tErr) {
      console.warn("[ApprovalGatekeeper] Thread ensure warning:", tErr);
    }

    let approvalId: string = randomUUID();
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
        `[ApprovalGatekeeper] 🎯 Thread ${threadId} 已存在挂起中的人工工单 (${approvalId})，无需重复创建！`,
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

  /**
   * 🎧 发起人工客服即时接管 (Start Human Support Takeover)
   */
  public static async startHumanTakeover(
    threadId = "default_thread",
    defaultUserId = "83d67d4e-104c-4325-8aa7-10d4389fc725",
  ): Promise<ProcessApprovalActionResult> {
    await db.createThread(threadId, defaultUserId);
    const drizzle = getDrizzle()!;

    const existing = await drizzle
      .select()
      .from(dbPendingApprovals)
      .where(eq(dbPendingApprovals.threadId, threadId))
      .orderBy(desc(dbPendingApprovals.createdAt))
      .limit(1);

    const threadRow = await drizzle
      .select({
        businessId: threads.businessId,
        userId: threads.userId,
        userEmail: users.email,
      })
      .from(threads)
      .leftJoin(users, sql`${threads.userId} = ${users.id}::text`)
      .where(eq(threads.id, threadId))
      .limit(1);

    const businessId = threadRow[0]?.businessId || "ecommerce";
    const threadUserId = threadRow[0]?.userId || undefined;
    const threadUserEmail = threadRow[0]?.userEmail || undefined;

    if (existing[0] && existing[0].status === "waiting") {
      return {
        success: true,
        approvalId: existing[0].id,
        approval: {
          ...existing[0],
          businessId,
          userId: threadUserId,
          userEmail: threadUserEmail,
        },
      };
    }

    const newId = randomUUID();
    const deadline = new Date(Date.now() + 1800000);
    const payload = {
      userInput: "客服随时主动接管实时对话",
      reason: "客服主动发起 IM 实时接管",
    };

    await drizzle.insert(dbPendingApprovals).values({
      id: newId,
      threadId,
      actionType: "human_escalation",
      actionPayload: payload,
      status: "waiting",
      deadline,
    });

    const sysMsgId = randomUUID();
    await db.addMessage({
      id: sysMsgId,
      threadId,
      role: "system",
      content:
        "【系统提示】人工客服已主动接入当前会话，您可以向客服发送消息进行实时沟通。",
      timestamp: new Date().toISOString(),
    });

    const newApproval = {
      id: newId,
      threadId,
      businessId,
      userId: threadUserId,
      userEmail: threadUserEmail,
      actionType: "human_escalation",
      actionPayload: payload,
      status: "waiting",
      deadline,
      createdAt: new Date().toISOString(),
    };

    return {
      success: true,
      approvalId: newId,
      approval: newApproval,
    };
  }

  /**
   * ⚡ 处理审批决议动作（封装分布式锁、状态更新、消息写入与断点续跑）
   */
  public static async processApprovalAction(
    options: ProcessApprovalActionOptions,
  ): Promise<ProcessApprovalActionResult> {
    const {
      approvalId,
      threadId,
      action,
      rejectionReason,
      humanReply,
      isFinish,
    } = options;

    if (action === "start_human_takeover") {
      return this.startHumanTakeover(threadId);
    }

    if (!approvalId || !action) {
      return {
        error: "approvalId and action are required",
        statusCode: 400,
      };
    }

    const lockKey = `lock:approval:${approvalId}`;
    let lockAcquired = false;
    let fallbackAcquired = false;

    if (useRedis && redis) {
      try {
        const result = await redis.set(lockKey, "locked", "PX", 5000, "NX");
        lockAcquired = result === "OK";
      } catch (err) {
        console.warn(
          "[ApprovalGatekeeper Lock] Redis SETNX failed, falling back to memory lock:",
          err,
        );
      }
    }

    if (!lockAcquired) {
      if (localLocks.has(lockKey)) {
        console.log(
          `[ApprovalGatekeeper Lock] 🎯 锁冲突拦截：工单 ${approvalId} 正在处理中...`,
        );
        return {
          error: "请勿重复提交，审批正在处理中...",
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

      const list = await drizzle
        .select()
        .from(dbPendingApprovals)
        .where(eq(dbPendingApprovals.id, approvalId))
        .limit(1);

      const record = list[0];
      if (!record) {
        return {
          error: `Approval工单 ${approvalId} 未找到`,
          statusCode: 404,
        };
      }

      if (record.status !== "waiting") {
        return {
          error: `工单 ${approvalId} 已经处理过，当前状态为: ${record.status}`,
          statusCode: 400,
        };
      }

      if (
        action === "human_message" ||
        (action === "human_reply" && isFinish === false)
      ) {
        if (humanReply && humanReply.trim()) {
          const msgId = randomUUID();
          await db.addMessage({
            id: msgId,
            threadId: record.threadId,
            role: "assistant",
            content: `[人工客服] ${humanReply.trim()}`,
            timestamp: new Date().toISOString(),
          });
          console.log(
            `[Human IM Chat] 人工客服回复已实时写入 thread: ${record.threadId}`,
          );
        }
        return {
          success: true,
          isHumanActive: true,
          threadId: record.threadId,
        };
      }

      let nextStatus = "rejected";
      if (action === "approve") {
        if (record.actionType === "human_escalation") {
          nextStatus = "resolved_by_human";
          const msgId = randomUUID();
          const replyContent =
            (humanReply && humanReply.trim()) ||
            "您好！人工客服专员已接入当前会话为您服务。请问有什么可以帮您？";
          await db.addMessage({
            id: msgId,
            threadId: record.threadId,
            role: "assistant",
            content: `[人工客服] ${replyContent}`,
            timestamp: new Date().toISOString(),
          });
        } else {
          nextStatus = "approved";
        }
      } else if (action === "cancel") {
        nextStatus = "cancelled";
      } else if (
        action === "human_finish" ||
        action === "human_reply" ||
        record.actionType === "human_escalation"
      ) {
        nextStatus = "resolved_by_human";

        if (humanReply && humanReply.trim()) {
          const msgId = randomUUID();
          await db.addMessage({
            id: msgId,
            threadId: record.threadId,
            role: "assistant",
            content: `[人工客服] ${humanReply.trim()}`,
            timestamp: new Date().toISOString(),
          });
        }

        const sysMsgId = randomUUID();
        await db.addMessage({
          id: sysMsgId,
          threadId: record.threadId,
          role: "system",
          content:
            "【系统提示】人工客服服务已结束，已成功为您切回 AI 智能助手。",
          timestamp: new Date().toISOString(),
        });
      }

      const updatedPayload = record.actionPayload
        ? {
            ...(record.actionPayload as Record<string, unknown>),
            rejectionReason: rejectionReason || "",
          }
        : { rejectionReason };

      const finalPayload = {
        ...updatedPayload,
        humanReply: humanReply || "",
      };

      // 🎯 确定性 Job ID 生成 (Deterministic Job ID Resumption):
      // 格式: job_resume_${approvalId}，确保重试和重放具备物理防重幂等性
      const deterministicJobId = `job_resume_${approvalId}`;
      const outboxEventId = randomUUID();

      let systemPromptText = "";
      if (nextStatus === "approved") {
        systemPromptText =
          "System: Human approval granted. Please execute the requested action.";
      } else if (nextStatus === "cancelled") {
        systemPromptText =
          "System: Human approval cancelled by the user. Please stop the requested action, abort any tool calls for this refund, and explain to the user that the action has been successfully cancelled per their request.";
      } else {
        systemPromptText = `System: Human approval rejected. Reason: ${rejectionReason || "Not policy compliant"}. Please replan alternative path.`;
      }

      let threadUserId = "83d67d4e-104c-4325-8aa7-10d4389fc725";
      try {
        const threadRows = await drizzle
          .select({ userId: threads.userId })
          .from(threads)
          .where(eq(threads.id, record.threadId))
          .limit(1);
        if (threadRows[0]?.userId) {
          threadUserId = threadRows[0].userId;
        }
      } catch (err) {
        console.warn(
          "[ApprovalGatekeeper] Failed to fetch thread userId via Drizzle, using record user_id fallback:",
          err,
        );
      }

      const eventType =
        nextStatus === "approved"
          ? "resume_execution"
          : nextStatus === "cancelled"
            ? "cancel_execution"
            : "reject_execution";

      const outboxPayload = {
        jobId: deterministicJobId,
        threadId: record.threadId,
        userId: threadUserId,
        systemPromptText,
        nextStatus,
      };

      // 🔒 事务发件箱 (Transactional Outbox Pattern)：
      // 将【工单状态更新】与【发件箱事件插入】封装在单一本地数据库事务中原子提交，杜绝幽灵审批
      await drizzle.transaction(async (tx) => {
        await tx
          .update(dbPendingApprovals)
          .set({
            status: nextStatus,
            actionPayload: finalPayload,
          })
          .where(eq(dbPendingApprovals.id, approvalId));

        if (nextStatus !== "resolved_by_human") {
          await tx.insert(approvalOutboxEvents).values({
            id: outboxEventId,
            approvalId,
            threadId: record.threadId,
            eventType,
            payload: outboxPayload,
            status: "pending",
            retryCount: 0,
            createdAt: new Date(),
            updatedAt: new Date(),
          });
        }
      });

      console.log(
        `[ApprovalGatekeeper] 成功人工处理工单 [ID: ${approvalId}] ➔ 决议为 [${nextStatus}] (Outbox Event: ${outboxEventId})`,
      );

      if (nextStatus === "resolved_by_human") {
        return {
          success: true,
          threadId: record.threadId,
          status: nextStatus,
        };
      }

      console.log(
        `[ApprovalGatekeeper] 正在快速通道恢复 thread ${record.threadId} 的 Agent 执行流... 确定性 JobID: ${deterministicJobId}`,
      );

      // ⚡ Fast-Path 同步派发：若成功则将 Outbox 事件标记为 completed；若失败则保留 pending 由对账 Worker 自动重试
      try {
        await WorkflowOrchestrator.dispatchJob({
          jobId: deterministicJobId,
          threadId: record.threadId,
          userId: threadUserId,
          message: systemPromptText,
        });

        await drizzle
          .update(approvalOutboxEvents)
          .set({
            status: "completed",
            updatedAt: new Date(),
          })
          .where(eq(approvalOutboxEvents.id, outboxEventId));
      } catch (dispatchErr: any) {
        console.warn(
          `[ApprovalGatekeeper Outbox] Fast-path dispatch failed for ${approvalId}, kept in pending status for reconciliation worker:`,
          dispatchErr?.message || String(dispatchErr),
        );
        await drizzle
          .update(approvalOutboxEvents)
          .set({
            status: "pending",
            errorMessage: dispatchErr?.message || String(dispatchErr),
            updatedAt: new Date(),
          })
          .where(eq(approvalOutboxEvents.id, outboxEventId));
      }

      return {
        success: true,
        jobId: deterministicJobId,
        threadId: record.threadId,
        status: nextStatus,
      };
    } catch (err: any) {
      console.warn("[ApprovalGatekeeper] Approval processing error:", err);
      return {
        error: `审批执行失败: ${err?.message || String(err)}`,
        statusCode: 500,
      };
    } finally {
      if (useRedis && redis && lockAcquired) {
        try {
          await redis.del(lockKey);
          console.log(
            `[ApprovalGatekeeper Lock] ✅ Redis 分布式锁已物理释放: ${lockKey}`,
          );
        } catch (err) {
          console.warn("[ApprovalGatekeeper Lock] Redis DEL failed:", err);
        }
      }
      if (fallbackAcquired) {
        localLocks.delete(lockKey);
        console.log(
          `[ApprovalGatekeeper Lock] ✅ 内存后备锁已物理释放: ${lockKey}`,
        );
      }
    }
  }
}

export const ApprovalPolicyEngine = ApprovalGatekeeper;
