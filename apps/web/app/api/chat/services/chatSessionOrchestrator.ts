import { db, getDrizzle, pendingApprovals, threads } from 'db';
import { and, eq } from 'drizzle-orm';
import {
  WorkflowOrchestrator,
  agentEventEmitter,
  currentPlanQuery,
  currentStatusQuery,
  getTemporalClient,
  isUsingMockTemporal,
} from 'engine';
import type { NextRequest } from 'next/server';
import { checkTenantQuotaGuard } from '../quotaGuard';

export interface ChatDispatchRequest {
  message?: string;
  input?: string;
  threadId?: string;
  userId?: string;
  businessId?: string;
  imageUrls?: string[];
  sync?: boolean;
  req?: NextRequest;
}

export interface ChatDispatchResult {
  success?: boolean;
  jobId?: string;
  threadId?: string;
  userId?: string;
  output?: string;
  result?: string;
  cards?: any[];
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

const inFlightRequests = globalForCache.inFlightRequests ?? new Map<string, string>();
const completedRequestsCache = globalForCache.completedRequestsCache ?? new Map<string, CachedJob>();

if (process.env.NODE_ENV !== 'production') {
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

/**
 * 🌟 ChatSessionOrchestrator 统一会话与事件流深模块 (Deep Module)
 * 职责：
 * 1. 租户配额检测与安全拦截 (Quota Guard)
 * 2. 人工客服主动接管状态检测与消息旁路落盘 (Human Takeover Bypass)
 * 3. 极速并发单飞去重 (Singleflight) 与 5s 精确提问哈希缓存 (Exact Cache)
 * 4. 多租户身份真实数据库物理溯源 (Tenant Identity Anchoring)
 * 5. 跨 Temporal / LangGraph 引擎统一分发 (WorkflowOrchestrator Dispatch)
 * 6. 统一 SSE 实时事件流与心跳保活帧封装 (SSE Event Streaming & Heartbeat)
 */
export class ChatSessionOrchestrator {
  /**
   * 🎧 校验会话是否存在活跃人工接管并直接持久化消息
   */
  public static async checkHumanTakeoverActive(threadId: string, message: string): Promise<boolean> {
    try {
      const drizzle = getDrizzle();
      if (!drizzle) return false;

      const activeApprovals = await drizzle
        .select()
        .from(pendingApprovals)
        .where(and(eq(pendingApprovals.threadId, threadId), eq(pendingApprovals.status, 'waiting')))
        .limit(1);

      if (activeApprovals.length === 0) return false;

      const activeApp = activeApprovals[0];
      const isHumanActive = activeApp.actionType?.includes('human') || activeApp.actionType?.includes('escalat');

      if (isHumanActive) {
        console.log(
          `[ChatSessionOrchestrator] 🎧 Active human support session detected for thread ${threadId}. Writing message directly to DB.`,
        );

        await db.addMessage({
          id:
            typeof crypto !== 'undefined' && crypto.randomUUID
              ? crypto.randomUUID()
              : Math.random().toString(36).substring(2, 15),
          threadId,
          role: 'user',
          content: message,
          timestamp: new Date().toISOString(),
        });

        return true;
      }
    } catch (hErr) {
      console.warn('[ChatSessionOrchestrator] Human takeover check warning:', hErr);
    }

    return false;
  }

  /**
   * 🚀 分发用户对话请求
   */
  public static async dispatchChatRequest(payload: ChatDispatchRequest): Promise<ChatDispatchResult> {
    pruneCaches();

    const effectiveMessage = (payload.message || payload.input || '').trim();
    const effectiveThreadId = payload.threadId || `thread_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
    const effectiveUserId = payload.userId || 'CUST-8801';
    const { businessId, imageUrls, req, sync } = payload;

    if (!effectiveMessage) {
      return { error: 'Message is required', statusCode: 400 };
    }
    if (!payload.threadId) {
      return { error: 'threadId is strictly required', statusCode: 400 };
    }
    if (!payload.userId) {
      return { error: 'userId is strictly required', statusCode: 400 };
    }

    const quotaCheck = await checkTenantQuotaGuard(effectiveUserId);
    if (!quotaCheck.allowed) {
      return {
        error: quotaCheck.reason || 'Quota limit exceeded',
        statusCode: 429,
      };
    }

    const isHumanActive = await this.checkHumanTakeoverActive(effectiveThreadId, effectiveMessage);
    if (isHumanActive) {
      return {
        success: true,
        threadId: effectiveThreadId,
        userId: effectiveUserId,
        isHumanActive: true,
      };
    }

    const cleanMessage = effectiveMessage.toLowerCase();
    const imageHash = imageUrls && imageUrls.length > 0 ? `:[images:${imageUrls.sort().join(',')}]` : '';
    const cacheKey = `${effectiveThreadId}:${cleanMessage}${imageHash}`;

    if (inFlightRequests.has(cacheKey)) {
      const existingJobId = inFlightRequests.get(cacheKey)!;
      console.log(`[Singleflight] 🎯 拦截到极速并发重复请求！直接合并至正在执行的 jobId: ${existingJobId}`);
      return {
        success: true,
        jobId: existingJobId,
        threadId: effectiveThreadId,
        userId: effectiveUserId,
        isCached: true,
      };
    }

    const now = Date.now();
    if (completedRequestsCache.has(cacheKey)) {
      const cached = completedRequestsCache.get(cacheKey)!;
      if (now - cached.timestamp < 5000) {
        console.log(`[Exact Cache Hit] 🎯 5秒内重复提问精确哈希去重命中！直接复用 jobId: ${cached.jobId}`);
        return {
          success: true,
          jobId: cached.jobId,
          threadId: effectiveThreadId,
          userId: effectiveUserId,
          isCached: true,
        };
      }
      completedRequestsCache.delete(cacheKey);
    }

    const jobId = `job_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
    inFlightRequests.set(cacheKey, jobId);

    // 🛡️ 多租户物理锚定：优先溯源数据库中该会话绑定的真实商户身份
    let effectiveBusinessId = businessId || 'aurora';
    if (effectiveThreadId) {
      try {
        const drizzle = getDrizzle();
        if (drizzle) {
          const threadRows = await drizzle.select().from(threads).where(eq(threads.id, effectiveThreadId)).limit(1);
          if (threadRows[0]?.businessId) {
            effectiveBusinessId = threadRows[0].businessId;
          }
        }
      } catch (err) {
        console.warn('[ChatSessionOrchestrator] Failed to resolve thread businessId:', err);
      }
    }

    const dispatchRes = await WorkflowOrchestrator.dispatchJob({
      jobId,
      threadId: effectiveThreadId,
      userId: effectiveUserId,
      message: effectiveMessage,
      businessId: effectiveBusinessId,
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
        console.log(`[Job Complete] ✅ Run ${jobId} completed. Registered in 5s short cache.`);
      })
      .catch((err) => {
        inFlightRequests.delete(cacheKey);
        console.warn(`[Job Fail] Run ${jobId} failed:`, err);
      });

    // 如果客户端请求同步返回结果 (如第三方商户 SDK / Widget 简易对接)
    if (sync) {
      try {
        const finalState = (await dispatchRes.promise) as any;
        return {
          success: true,
          jobId,
          threadId: effectiveThreadId,
          userId: effectiveUserId,
          output: finalState?.output || finalState?.result || '智能客服已为您处理完毕。',
          result: finalState?.output || finalState?.result || '智能客服已为您处理完毕。',
          cards: finalState?.cards || [],
          isTemporalMode: dispatchRes.isTemporalMode,
        };
      } catch (execErr: any) {
        return {
          error: execErr?.message || 'Agent execution failed',
          statusCode: 500,
        };
      }
    }

    return {
      success: true,
      jobId,
      threadId: effectiveThreadId,
      userId: effectiveUserId,
      isTemporalMode: dispatchRes.isTemporalMode,
    };
  }

  /**
   * 🌊 统一创建 SSE 实时事件流 (ReadableStream)
   */
  public static createEventStream(options: {
    jobId: string;
    signal?: AbortSignal;
  }): ReadableStream {
    const { jobId, signal } = options;
    const isMock = isUsingMockTemporal();

    return new ReadableStream({
      async start(controller) {
        const sendSSE = (event: string, data: unknown) => {
          try {
            controller.enqueue(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
          } catch {
            // Controller might be closed
          }
        };

        if (!isMock) {
          let pollInterval: NodeJS.Timeout | null = null;
          let lastStatus = '';
          try {
            sendSSE('status', {
              status: 'running',
              message: 'Temporal 工作流引擎已接管调度，正在初始化...',
            });
            const client = await getTemporalClient();
            const handle = client.workflow.getHandle(jobId);

            pollInterval = setInterval(async () => {
              try {
                const [status, plan] = await Promise.all([
                  handle.query(currentStatusQuery).catch(() => null),
                  handle.query(currentPlanQuery).catch(() => null),
                ]);

                if (status && status !== lastStatus) {
                  lastStatus = status;
                  sendSSE('status', {
                    status: 'executing',
                    message: status,
                    plan: plan || undefined,
                  });
                }
              } catch {
                // Ignore query errors during transition or completion
              }
            }, 300);

            const result = await handle.result();
            if (pollInterval) clearInterval(pollInterval);
            sendSSE('result', result);
            controller.close();
          } catch (err) {
            if (pollInterval) clearInterval(pollInterval);
            console.error('[Temporal SSE] failed:', err);
            sendSSE('error', {
              message: err instanceof Error ? err.message : 'Temporal workflow execution failed',
            });
            controller.close();
          }
          return;
        }

        // Local LangGraph Direct Mode
        let unsubscribe = () => {};

        const subscriptionTimeout = setTimeout(() => {
          unsubscribe = agentEventEmitter.playbackAndSubscribe(
            jobId,
            (statusData) => {
              sendSSE('status', statusData);
            },
            (resultData) => {
              sendSSE('result', resultData);
              unsubscribe();
              agentEventEmitter.clearJob(jobId);
              try {
                controller.close();
              } catch {}
            },
          );
        }, 150);

        const heartbeat = setInterval(() => {
          try {
            controller.enqueue(': heartbeat\n\n');
          } catch {
            clearInterval(heartbeat);
          }
        }, 15000);

        if (signal) {
          signal.addEventListener('abort', () => {
            clearTimeout(subscriptionTimeout);
            clearInterval(heartbeat);
            unsubscribe();
          });
        }
      },
    });
  }
}

export const ChatSessionService = ChatSessionOrchestrator;
export const checkHumanTakeoverActive = ChatSessionOrchestrator.checkHumanTakeoverActive.bind(ChatSessionOrchestrator);
export const dispatchChatRequest = ChatSessionOrchestrator.dispatchChatRequest.bind(ChatSessionOrchestrator);
