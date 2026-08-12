import { db, getDrizzle, pendingApprovals, threads } from "db";
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
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error fetching approvals:", error);
    return NextResponse.json(
      { error: errMsg || "Internal Server Error" },
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
    const body = await req.json();
    const {
      approvalId,
      threadId,
      action,
      rejectionReason,
      humanReply,
      isFinish,
    } = body;

    // 客服随时主动发起 IM 接管请求
    if (action === "start_human_takeover") {
      const activeThreadId = threadId || "default_thread";
      const drizzle = getDrizzle()!;

      // 1. 查找是否有已存在的挂起工单
      const existing = await drizzle
        .select()
        .from(pendingApprovals)
        .where(eq(pendingApprovals.threadId, activeThreadId))
        .orderBy(desc(pendingApprovals.createdAt))
        .limit(1);

      if (existing[0] && existing[0].status === "waiting") {
        return NextResponse.json({
          success: true,
          approvalId: existing[0].id,
          approval: existing[0],
        });
      }

      // 2. 物理创建主动接管工单
      const newId = `app_takeover_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`;
      const deadline = new Date(Date.now() + 1800000).toISOString();
      const payload = {
        userInput: "客服随时主动接管实时对话",
        reason: "客服主动发起 IM 实时接管",
      };

      await drizzle.insert(pendingApprovals).values({
        id: newId,
        threadId: activeThreadId,
        actionType: "human_escalation",
        actionPayload: payload,
        status: "waiting",
        deadline,
      });

      const sysMsgId = crypto.randomUUID
        ? crypto.randomUUID()
        : require("node:crypto").randomUUID();
      await db.addMessage({
        id: sysMsgId,
        threadId: activeThreadId,
        role: "system",
        content:
          "【系统提示】人工客服已主动接入当前会话，您可以向客服发送消息进行实时沟通。",
        timestamp: new Date().toISOString(),
      });

      const newApproval = {
        id: newId,
        threadId: activeThreadId,
        actionType: "human_escalation",
        actionPayload: payload,
        status: "waiting",
        deadline,
        createdAt: new Date().toISOString(),
      };

      return NextResponse.json({
        success: true,
        approvalId: newId,
        approval: newApproval,
      });
    }

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
      setTimeout(() => {
        localLocks.delete(lockKey);
      }, 10000);
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

      // 5. 人工实时聊天模式 (human_message / isFinish === false)
      if (
        action === "human_message" ||
        (action === "human_reply" && isFinish === false)
      ) {
        if (humanReply && humanReply.trim()) {
          const msgId = crypto.randomUUID
            ? crypto.randomUUID()
            : require("node:crypto").randomUUID();
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
        return NextResponse.json({
          success: true,
          isHumanActive: true,
          threadId: record.threadId,
        });
      }

      // 6. 更新审批状态 (结束人工会话/核准/驳回/取消)
      let nextStatus = "rejected";
      if (action === "approve") {
        nextStatus = "approved";
      } else if (action === "cancel") {
        nextStatus = "cancelled";
      } else if (
        action === "human_finish" ||
        action === "human_reply" ||
        record.actionType === "human_escalation"
      ) {
        nextStatus = "resolved_by_human";

        // 写入最终人工回复和系统切回提示
        if (humanReply && humanReply.trim()) {
          const msgId = crypto.randomUUID
            ? crypto.randomUUID()
            : require("node:crypto").randomUUID();
          await db.addMessage({
            id: msgId,
            threadId: record.threadId,
            role: "assistant",
            content: `[人工客服] ${humanReply.trim()}`,
            timestamp: new Date().toISOString(),
          });
        }

        const sysMsgId = crypto.randomUUID
          ? crypto.randomUUID()
          : require("node:crypto").randomUUID();
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
            ...(record.actionPayload as any),
            rejectionReason: rejectionReason || "",
          }
        : { rejectionReason };

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

      // 人工服务结束模式：直接返回成功，无需重触发 AI Agent 执行图
      if (nextStatus === "resolved_by_human") {
        return NextResponse.json({
          success: true,
          threadId: record.threadId,
          status: nextStatus,
        });
      }

      // 6. 产生一个新的 jobId，用于让前端订阅恢复决策流之后的 SSE 状态推送
      const jobId = `job_resume_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;

      // 7. 真正拉起并恢复 Agent 执行 (用于工具审批放行/驳回/取消等 HITL 流程)
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

      console.log(
        `[Approval POST] 正在恢复 thread ${record.threadId} 的 Agent 执行流... 新 jobId: ${jobId}`,
      );

      // 🔍 物理关联所属用户 UUID，防止恢复时降级为 default_user 造成多租户长期记忆交叉污染
      let threadUserId = "83d67d4e-104c-4325-8aa7-10d4389fc725"; // Fallback seed user
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
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error handling approval action:", error);
    return NextResponse.json(
      { error: errMsg || "Internal Server Error" },
      { status: 500 },
    );
  }
}
