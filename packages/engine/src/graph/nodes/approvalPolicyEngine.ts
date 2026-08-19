import { db, getDrizzle, pendingApprovals as dbPendingApprovals } from "db";
import { desc, eq } from "drizzle-orm";
import type { PendingApprovalRecord } from "../state";

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

/**
 * 🛡️ 校验重复退款防护 (Double-Refund Prevention)
 */
export async function checkDoubleRefund(
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
    console.warn("[ApprovalPolicyEngine] Double refund check DB error:", err);
  }
  return { isDoubleRefund: false };
}

/**
 * 🪙 评估退款免签额度 (Refund Auto-Approval Threshold Evaluation)
 */
export async function evaluateRefundAutoApproval(
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
      console.warn("[ApprovalPolicyEngine] Grounding order amount error:", err);
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
export async function evaluateAddressChangePolicy(
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
    console.warn("[ApprovalPolicyEngine] Address policy DB error:", err);
  }

  return { isHighValue: false, totalAmount: 0 };
}

/**
 * 🔍 通过工单 ID 查询审批详情 (纯领域门面，不泄漏 ORM 查询构造器)
 */
export async function findApprovalById(
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
    console.warn("[ApprovalPolicyEngine] findApprovalById DB error:", err);
  }
  return null;
}

/**
 * 🔍 查询会话最新的待审核/已审核工单记录 (纯领域门面)
 */
export async function findLatestApprovalByThreadId(
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
      "[ApprovalPolicyEngine] findLatestApprovalByThreadId DB error:",
      err,
    );
  }
  return null;
}

/**
 * ⏰ 人工工单状态机与超时熔断校验 (Pending Approval Lifecycle & Timeout Engine)
 */
export async function evaluatePendingApprovalState(opts: {
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
    const newApprovalId = crypto.randomUUID
      ? crypto.randomUUID()
      : Math.random().toString(36).substring(2, 15);
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

export const ApprovalPolicyEngine = {
  checkDoubleRefund,
  evaluateRefundAutoApproval,
  evaluateAddressChangePolicy,
  evaluatePendingApprovalState,
  findApprovalById,
  findLatestApprovalByThreadId,
};
