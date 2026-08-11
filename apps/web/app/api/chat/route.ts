import { getTemporalClient, isUsingMockTemporal, runAgent } from "engine";
import { type NextRequest, NextResponse } from "next/server";

interface CachedJob {
  jobId: string;
  timestamp: number;
}

// Support hot reload persistence in Next.js development server
const globalForCache = global as unknown as {
  inFlightRequests?: Map<string, string>; // threadId:cleanMessage -> jobId
  completedRequestsCache?: Map<string, CachedJob>; // threadId:cleanMessage -> CachedJob
};

const inFlightRequests =
  globalForCache.inFlightRequests ?? new Map<string, string>();
const completedRequestsCache =
  globalForCache.completedRequestsCache ?? new Map<string, CachedJob>();

if (process.env.NODE_ENV !== "production") {
  globalForCache.inFlightRequests = inFlightRequests;
  globalForCache.completedRequestsCache = completedRequestsCache;
}

export async function POST(req: NextRequest) {
  try {
    const { message, threadId, userId } = await req.json();

    if (!message) {
      return NextResponse.json(
        { error: "Message is required" },
        { status: 400 },
      );
    }

    // 🛡️ 最底层的多租户会话隔离防卫：无 threadId 或 userId 直接物理拒绝处理！
    if (!threadId) {
      return NextResponse.json(
        { error: "threadId is strictly required" },
        { status: 400 },
      );
    }
    if (!userId) {
      return NextResponse.json(
        { error: "userId is strictly required" },
        { status: 400 },
      );
    }

    const cleanMessage = message.trim().toLowerCase();
    const cacheKey = `${threadId}:${cleanMessage}`;

    // =========================================================================
    // 🛡️ Step 0: In-flight Singleflight 并发请求合并 (Request Collapsing)
    // =========================================================================
    if (inFlightRequests.has(cacheKey)) {
      const existingJobId = inFlightRequests.get(cacheKey)!;
      console.log(
        `[Singleflight] 🎯 拦截到极速并发重复请求！直接合并至正在执行的 jobId: ${existingJobId}`,
      );
      return NextResponse.json({
        success: true,
        jobId: existingJobId,
        threadId,
        userId,
        isCached: true,
      });
    }

    // =========================================================================
    // 🛡️ Step 1: 精确文本哈希去重 (短 TTL 5秒缓存 - 防止重复快速点击)
    // =========================================================================
    const now = Date.now();
    if (completedRequestsCache.has(cacheKey)) {
      const cached = completedRequestsCache.get(cacheKey)!;
      if (now - cached.timestamp < 5000) {
        console.log(
          `[Exact Cache Hit] 🎯 5秒内重复提问精确哈希去重命中！直接复用 jobId: ${cached.jobId}`,
        );
        return NextResponse.json({
          success: true,
          jobId: cached.jobId,
          threadId,
          userId,
          isCached: true,
        });
      }
      completedRequestsCache.delete(cacheKey);
    }

    const jobId = `job_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

    // 标记当前请求为 In-flight 执行中
    inFlightRequests.set(cacheKey, jobId);

    // Try to connect to Temporal first
    const client = await getTemporalClient();
    const isMock = isUsingMockTemporal();

    if (!isMock) {
      console.log(
        `[Temporal] Connecting successfully. Starting workflow ${jobId} on queue 'agent-tasks'...`,
      );
      const workflowPromise = client.workflow.start("agentWorkflow", {
        taskQueue: "agent-tasks",
        workflowId: jobId,
        args: [threadId, userId, message],
      });

      workflowPromise
        .then((handle) => {
          handle
            .result()
            .then(() => {
              inFlightRequests.delete(cacheKey);
              completedRequestsCache.set(cacheKey, {
                jobId,
                timestamp: Date.now(),
              });
              console.log(
                `[Temporal Complete] ✅ Workflow ${jobId} completed. Registered in 5s short cache.`,
              );
            })
            .catch((err) => {
              inFlightRequests.delete(cacheKey);
              console.warn(
                `[Temporal Fail] Workflow ${jobId} execution failed:`,
                err,
              );
            });
        })
        .catch((err) => {
          inFlightRequests.delete(cacheKey);
          console.error("[Temporal Start Fail] Failed to start workflow:", err);
        });
    } else {
      console.log(
        `[Local Engine] Temporal connection not ready. Routing execution directly to local LangGraph StateGraph with jobId: ${jobId}...`,
      );
      // Fallback: Trigger local graph execution and store the promise/state globally
      const executionPromise = runAgent(threadId, userId, message, jobId);

      // 🛡️ Serverless container-freeze protection:
      // If deployed on serverless environments (e.g. Vercel, Cloudflare, Next.js Edge),
      // we must declare the promise to the request runtime context so the serverless container
      // does not freeze or go to sleep mid-execution before the LangGraph completes.
      if ((req as any).waitUntil) {
        (req as any).waitUntil(executionPromise);
      }

      if (typeof global !== "undefined") {
        if (!(global as any).agentRuns) {
          (global as any).agentRuns = new Map();
        }
        (global as any).agentRuns.set(jobId, executionPromise);
      }

      // 注册 Promise 监听器进行去重生命周期管理
      executionPromise
        .then(() => {
          inFlightRequests.delete(cacheKey);
          completedRequestsCache.set(cacheKey, {
            jobId,
            timestamp: Date.now(),
          });
          console.log(
            `[Local Complete] ✅ Local run ${jobId} completed. Registered in 5s short cache.`,
          );
        })
        .catch((err) => {
          inFlightRequests.delete(cacheKey);
          console.warn(`[Local Fail] Local run ${jobId} failed:`, err);
        });
    }

    return NextResponse.json({
      success: true,
      jobId,
      threadId,
      userId,
      isTemporalMode: !isMock,
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error in POST /api/chat endpoint:", error);
    return NextResponse.json(
      { error: errMsg || "Internal Server Error" },
      { status: 500 },
    );
  }
}
