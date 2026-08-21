import { db, getDrizzle, pendingApprovals } from "db";
import { and, eq } from "drizzle-orm";
import { WorkflowOrchestrator } from "engine";
import type { NextRequest } from "next/server";
import { checkTenantQuotaGuard } from "../quotaGuard";

export interface ChatDispatchRequest {
  message?: string;
  threadId?: string;
  userId?: string;
  imageUrls?: string[];
  req?: NextRequest;
}

export interface ChatDispatchResult {
  success?: boolean;
  jobId?: string;
  threadId?: string;
  userId?: string;
  isCached?: boolean;
  isHumanActive?: boolean;
  isTemporalMode?: boolean;
  error?: string;
  statusCode?: number;
}

interface CachedJob {
  jobId: string;
  timestamp: number;
}

const globalForCache = global as unknown as {
  inFlightRequests?: Map<string, string>;
  completedRequestsCache?: Map<string, CachedJob>;
};

const inFlightRequests =
  globalForCache.inFlightRequests ?? new Map<string, string>();
const completedRequestsCache =
  globalForCache.completedRequestsCache ?? new Map<string, CachedJob>();

if (process.env.NODE_ENV !== "production") {
  globalForCache.inFlightRequests = inFlightRequests;
  globalForCache.completedRequestsCache = completedRequestsCache;
}

function pruneCaches(): void {
  const now = Date.now();
  const CACHE_TTL_MS = 5 * 60 * 1000;
  for (const [key, value] of Array.from(completedRequestsCache.entries())) {
    if (now - value.timestamp > CACHE_TTL_MS) {
      completedRequestsCache.delete(key);
    }
  }
  if (completedRequestsCache.size > 1000) {
    const firstKey = Array.from(completedRequestsCache.keys())[0];
    if (firstKey) completedRequestsCache.delete(firstKey);
  }
}

export async function checkHumanTakeoverActive(
  threadId: string,
  message: string,
): Promise<boolean> {
  try {
    const drizzle = getDrizzle();
    if (!drizzle) return false;

    const activeApprovals = await drizzle
      .select()
      .from(pendingApprovals)
      .where(
        and(
          eq(pendingApprovals.threadId, threadId),
          eq(pendingApprovals.status, "waiting"),
        ),
      )
      .limit(1);

    if (activeApprovals.length === 0) return false;

    const activeApp = activeApprovals[0];
    const isHumanActive =
      activeApp.actionType?.includes("human") ||
      activeApp.actionType?.includes("escalat");

    if (isHumanActive) {
      console.log(
        `[ChatSessionService] 🎧 Active human support session detected for thread ${threadId}. Writing message directly to DB.`,
      );

      await db.addMessage({
        id:
          typeof crypto !== "undefined" && crypto.randomUUID
            ? crypto.randomUUID()
            : Math.random().toString(36).substring(2, 15),
        threadId,
        role: "user",
        content: message,
        timestamp: new Date().toISOString(),
      });

      return true;
    }
  } catch (hErr) {
    console.warn("[ChatSessionService] Human takeover check warning:", hErr);
  }

  return false;
}

export async function dispatchChatRequest(
  payload: ChatDispatchRequest,
): Promise<ChatDispatchResult> {
  pruneCaches();

  const { message, threadId, userId, imageUrls, req } = payload;

  if (!message) {
    return { error: "Message is required", statusCode: 400 };
  }
  if (!threadId) {
    return { error: "threadId is strictly required", statusCode: 400 };
  }
  if (!userId) {
    return { error: "userId is strictly required", statusCode: 400 };
  }

  const quotaCheck = await checkTenantQuotaGuard(userId);
  if (!quotaCheck.allowed) {
    return {
      error: quotaCheck.reason || "Quota limit exceeded",
      statusCode: 429,
    };
  }

  const isHumanActive = await checkHumanTakeoverActive(threadId, message);
  if (isHumanActive) {
    return {
      success: true,
      threadId,
      userId,
      isHumanActive: true,
    };
  }

  const cleanMessage = message.trim().toLowerCase();
  const imageHash =
    imageUrls && imageUrls.length > 0
      ? `:[images:${imageUrls.sort().join(",")}]`
      : "";
  const cacheKey = `${threadId}:${cleanMessage}${imageHash}`;

  if (inFlightRequests.has(cacheKey)) {
    const existingJobId = inFlightRequests.get(cacheKey)!;
    console.log(
      `[Singleflight] 🎯 拦截到极速并发重复请求！直接合并至正在执行的 jobId: ${existingJobId}`,
    );
    return {
      success: true,
      jobId: existingJobId,
      threadId,
      userId,
      isCached: true,
    };
  }

  const now = Date.now();
  if (completedRequestsCache.has(cacheKey)) {
    const cached = completedRequestsCache.get(cacheKey)!;
    if (now - cached.timestamp < 5000) {
      console.log(
        `[Exact Cache Hit] 🎯 5秒内重复提问精确哈希去重命中！直接复用 jobId: ${cached.jobId}`,
      );
      return {
        success: true,
        jobId: cached.jobId,
        threadId,
        userId,
        isCached: true,
      };
    }
    completedRequestsCache.delete(cacheKey);
  }

  const jobId = `job_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
  inFlightRequests.set(cacheKey, jobId);

  const dispatchRes = await WorkflowOrchestrator.dispatchJob({
    jobId,
    threadId,
    userId,
    message,
    imageUrls,
    req,
  });

  dispatchRes.promise
    .then(() => {
      inFlightRequests.delete(cacheKey);
      completedRequestsCache.set(cacheKey, {
        jobId,
        timestamp: Date.now(),
      });
      console.log(
        `[Job Complete] ✅ Run ${jobId} completed. Registered in 5s short cache.`,
      );
    })
    .catch((err) => {
      inFlightRequests.delete(cacheKey);
      console.warn(`[Job Fail] Run ${jobId} failed:`, err);
    });

  return {
    success: true,
    jobId,
    threadId,
    userId,
    isTemporalMode: dispatchRes.isTemporalMode,
  };
}

export const ChatSessionService = {
  dispatchChatRequest,
  checkHumanTakeoverActive,
};
