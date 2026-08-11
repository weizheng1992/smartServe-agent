import { getDrizzle, pendingApprovals, threads } from "db";
import { desc, eq } from "drizzle-orm";
import { runAgent } from "engine";
import { type NextRequest, NextResponse } from "next/server";
import { redis, useRedis } from "tools";

// 内存后备锁集合，用于 Redis 离线或异常时的降级锁防护
const localLocks = new Set<string>();

// GET /api/chat/approvals - 获取所有挂起的审批工单（带商户关联）
export async function GET(req: NextRequest) {
  try {
    const drizzle = getDrizzle()!;
    const list = await drizzle
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
    return NextResponse.json({ success: true, approvals: list });
  } catch (error: any) {
    console.error("Error fetching approvals:", error);
    return NextResponse.json(
      { error: error.message || "Internal Server Error" },
      { status: 500 },
    );
  }
}

// POST /api/chat/approvals - 核准或驳回审批工单，并安全恢复 Agent 决策执行
export async function POST(req: NextRequest) {
  let lockKey = "";
  let lockAcquired = false;
  let fallbackAcquired = false;

  try {
    const { approvalId, action, rejectionReason, humanReply } =
      await req.json();

    if (!approvalId || !action) {
      return NextResponse.json(
        { error: "approvalId and action are required" },
        { status: 400 },
      );
    }

    lockKey = `lock:approval:${approvalId}`;

    // 1. 尝试使用 Redis SETNX 加分布式锁，防止并发点击冲突
    if (useRedis && redis) {
      try {
        const result = await redis.set(lockKey, "locked", "PX", 5000, "NX");
        lockAcquired = result === "OK";
      } catch (err) {
        console.warn(
          "[Approval Lock] Redis SETNX failed, falling back to memory lock:",
          err,
        );
      }
    }

    // 2. 如果 Redis 连接未建立或获取失败，降级使用内存 Set 进行锁防护
    if (!lockAcquired) {
      if (localLocks.has(lockKey)) {
        console.log(
          `[Approval Lock] 🎯 锁冲突拦截：工单 ${approvalId} 正在处理中...`,
        );
        return NextResponse.json(
          { error: "请勿重复提交，审批正在处理中..." },
          { status: 409 },
        );
      }
      localLocks.add(lockKey);
      fallbackAcquired = true;
    }

    try {
      const drizzle = getDrizzle()!;

      // 3. 查询审批工单
      const list = await drizzle
        .select()
        .from(pendingApprovals)
        .where(eq(pendingApprovals.id, approvalId))
        .limit(1);

      const record = list[0];
      if (!record) {
        return NextResponse.json(
          { error: `Approval工单 ${approvalId} 未找到` },
          { status: 404 },
        );
      }

      // 4. 幂等性强校验：如果工单状态不为 waiting，说明已被并发处理完成，直接返回失败
      if (record.status !== "waiting") {
        return NextResponse.json(
          {
            error: `工单 ${approvalId} 已经处理过，当前状态为: ${record.status}`,
          },
          { status: 400 },
        );
      }

      // 5. 更新审批状态
      const updatedPayload = record.actionPayload
        ? {
            ...(record.actionPayload as any),
            rejectionReason: rejectionReason || "",
          }
        : { rejectionReason };

      let nextStatus = "rejected";
      if (action === "approve") {
        nextStatus = "approved";
      } else if (action === "cancel") {
        nextStatus = "cancelled";
      } else if (
        action === "human_reply" ||
        record.actionType === "human_escalation"
      ) {
        nextStatus = "resolved_by_human";
      }

      const finalPayload = {
        ...updatedPayload,
        humanReply: humanReply || "",
      };

      await drizzle
        .update(pendingApprovals)
        .set({
          status: nextStatus,
          actionPayload: finalPayload,
        })
        .where(eq(pendingApprovals.id, approvalId));

      console.log(
        `[Approval POST] 成功人工处理工单 [ID: ${approvalId}] ➔ 决议为 [${nextStatus}]`,
      );

      // 6. 产生一个新的 jobId，用于让前端订阅恢复决策流之后的 SSE 状态推送
      const jobId = `job_resume_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;

      // 7. 真正拉起并恢复 Agent 执行
      let systemPromptText = "";
      if (nextStatus === "resolved_by_human") {
        const replyText = humanReply || "人工客服已接管并处理了您的请求。";
        systemPromptText = `System: Human support operator responded to the user: "${replyText}". Please present this response politely to the user in Chinese and resume normal support.`;
      } else if (nextStatus === "approved") {
        systemPromptText =
          "System: Human approval granted. Please execute the requested action.";
      } else if (nextStatus === "cancelled") {
        systemPromptText =
          "System: Human approval cancelled by the user. Please stop the requested action, abort any tool calls for this refund, and explain to the user that the action has been successfully cancelled per their request.";
      } else {
        systemPromptText = `System: Human approval rejected. Reason: ${rejectionReason || "Not policy compliant"}. Please replan alternative path.`;
      }

      console.log(
        `[Approval POST] 正在恢复 thread ${record.threadId} 的 Agent 执行流... 新 jobId: ${jobId}`,
      );

      // 🔍 物理关联所属用户 UUID，防止恢复时降级为 default_user 造成多租户长期记忆交叉污染
      let threadUserId = "83d67d4e-104c-4325-8aa7-10d4389fc725"; // Fallback seed user
      try {
        const { threads: dbThreads, getDrizzle } = require("db");
        const { eq: drizzleEq } = require("drizzle-orm");
        const dbInstance = getDrizzle()!;
        const threadRows = await dbInstance
          .select({ userId: dbThreads.userId })
          .from(dbThreads)
          .where(drizzleEq(dbThreads.id, record.threadId))
          .limit(1);
        if (threadRows[0]?.userId) {
          threadUserId = threadRows[0].userId;
        }
      } catch (err) {
        console.warn(
          "[Approval Route] Failed to fetch thread userId via Drizzle, using record user_id fallback:",
          err,
        );
      }

      // 直接恢复 Agent 执行（非阻塞）
      const executionPromise = runAgent(
        record.threadId,
        threadUserId,
        systemPromptText,
        jobId,
      );

      if (typeof global !== "undefined") {
        if (!(global as any).agentRuns) {
          (global as any).agentRuns = new Map();
        }
        (global as any).agentRuns.set(jobId, executionPromise);
      }

      return NextResponse.json({
        success: true,
        jobId,
        threadId: record.threadId,
        status: nextStatus,
      });
    } finally {
      // 8. 物理释放分布式锁或内存降级锁
      if (useRedis && redis && lockAcquired) {
        try {
          await redis.del(lockKey);
          console.log(
            `[Approval Lock] ✅ Redis 分布式锁已物理释放: ${lockKey}`,
          );
        } catch (err) {
          console.warn("[Approval Lock] Redis DEL failed:", err);
        }
      }
      if (fallbackAcquired) {
        localLocks.delete(lockKey);
        console.log(`[Approval Lock] ✅ 内存后备锁已物理释放: ${lockKey}`);
      }
    }
  } catch (error: any) {
    console.error("Error handling approval action:", error);
    return NextResponse.json(
      { error: error.message || "Internal Server Error" },
      { status: 500 },
    );
  }
}
