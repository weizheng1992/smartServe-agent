import { BadRequestException, Injectable } from '@nestjs/common';
import { IsArray, IsBoolean, IsOptional, IsString } from 'class-validator';
import { ConversationRepository, getPgPool } from 'db';
import {
  WorkflowOrchestrator,
  agentEventEmitter,
  currentPlanQuery,
  currentStatusQuery,
  getTemporalClient,
  isUsingMockTemporal,
} from 'engine';
import type { Response } from 'express';
import { logger } from 'observability';

export class DispatchChatDto {
  @IsOptional()
  @IsString()
  message?: string;

  @IsOptional()
  @IsString()
  input?: string;

  @IsOptional()
  @IsString()
  threadId?: string;

  @IsOptional()
  @IsString()
  userId?: string;

  @IsOptional()
  @IsString()
  businessId?: string;

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  imageUrls?: string[];

  @IsOptional()
  @IsBoolean()
  sync?: boolean;
}

export interface SseEventItem {
  id: number;
  event: string;
  data: any;
  timestamp: number;
}

interface JobEventBuffer {
  seq: number;
  events: SseEventItem[];
  lastAccessedAt: number;
  completed?: boolean;
  activeResponses: Set<Response>;
}

@Injectable()
export class ChatService {
  /**
   * 跨连接共享的 Job 级 SSE 事件缓存池 (用于支持 Last-Event-ID 断线续传)
   */
  private static readonly jobEventStore = new Map<string, JobEventBuffer>();

  /**
   * 获取或初始化 Job 的事件缓存队列
   */
  private static getOrCreateJobBuffer(jobId: string): JobEventBuffer {
    ChatService.pruneOldJobBuffers();
    let buffer = ChatService.jobEventStore.get(jobId);
    if (!buffer) {
      buffer = {
        seq: 0,
        events: [],
        lastAccessedAt: Date.now(),
        activeResponses: new Set<Response>(),
      };
      ChatService.jobEventStore.set(jobId, buffer);
    } else {
      buffer.lastAccessedAt = Date.now();
    }
    return buffer;
  }

  /**
   * 记录事件到 Job 缓存并广播给所有当前在线的连接
   */
  public static recordEvent(jobId: string, event: string, data: any): SseEventItem {
    const jobBuffer = ChatService.getOrCreateJobBuffer(jobId);
    jobBuffer.seq++;
    const currentSeq = jobBuffer.seq;
    const payload: SseEventItem = {
      id: currentSeq,
      event,
      data,
      timestamp: Date.now(),
    };
    jobBuffer.events.push(payload);
    // 保留最近 100 条事件以备断线补发
    if (jobBuffer.events.length > 100) jobBuffer.events.shift();

    const chunk = `id: ${currentSeq}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    for (const res of jobBuffer.activeResponses) {
      try {
        res.write(chunk);
      } catch (err) {
        logger.warn({ err, jobId }, '[ChatService] SSE active write error');
      }
    }

    return payload;
  }

  /**
   * 定期清理超过 10 分钟无访问的 Job 缓存
   */
  private static pruneOldJobBuffers() {
    const now = Date.now();
    const TTL = 10 * 60 * 1000;
    for (const [jid, buf] of ChatService.jobEventStore.entries()) {
      if (now - buf.lastAccessedAt > TTL && buf.activeResponses.size === 0) {
        ChatService.jobEventStore.delete(jid);
      }
    }
  }

  /**
   * 分发 Agent 对话任务
   */
  async dispatchChat(dto: DispatchChatDto) {
    const effectiveMessage = (dto.message || dto.input || '').trim();
    if (!effectiveMessage) {
      throw new BadRequestException('Message is required');
    }

    const effectiveThreadId = dto.threadId || `thread_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
    const effectiveUserId = dto.userId || 'CUST-8801';
    const effectiveBusinessId = dto.businessId || 'ecommerce';
    const jobId = `job_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;

    // 1. 持久化记录用户消息到 messages 表
    await ConversationRepository.appendMessage({
      threadId: effectiveThreadId,
      businessId: effectiveBusinessId,
      userId: effectiveUserId,
      role: 'user',
      content: effectiveMessage,
    });

    // 2. 调用 WorkflowOrchestrator 分发作业
    const dispatchRes = await WorkflowOrchestrator.dispatchJob({
      jobId,
      threadId: effectiveThreadId,
      userId: effectiveUserId,
      message: effectiveMessage,
      businessId: effectiveBusinessId,
      imageUrls: dto.imageUrls,
    });

    // 3. 异步监听完成事件，将最终回复写入数据库
    dispatchRes.promise
      .then(async (finalState: any) => {
        const replyContent = finalState?.output || finalState?.result || '智能客服已为您处理完毕。';
        await ConversationRepository.appendMessage({
          threadId: effectiveThreadId,
          businessId: effectiveBusinessId,
          role: 'assistant',
          content: replyContent,
          cards: finalState?.cards || [],
        });
      })
      .catch((err) => {
        logger.warn({ err, jobId }, '[ChatService] Agent job execution failed');
      });

    if (dto.sync) {
      const finalState: any = await dispatchRes.promise;
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
   * 管道化处理 SSE 实时推流（支持 EventId 序列号递增与 Last-Event-ID 重放）
   */
  pipeSSE(jobId: string, res: Response, lastEventId?: string) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache, no-transform');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.flushHeaders?.();

    const jobBuffer = ChatService.getOrCreateJobBuffer(jobId);

    // 检查断线重连回放 (Replay missed events if client provides lastEventId)
    if (lastEventId) {
      const lastIdNum = Number.parseInt(lastEventId, 10);
      if (!Number.isNaN(lastIdNum)) {
        const missedEvents = jobBuffer.events.filter((e) => e.id > lastIdNum);
        for (const missed of missedEvents) {
          try {
            res.write(`id: ${missed.id}\nevent: ${missed.event}\ndata: ${JSON.stringify(missed.data)}\n\n`);
          } catch (err) {
            logger.warn({ err, jobId }, '[ChatService] SSE replay write error');
          }
        }
      }
    }

    jobBuffer.activeResponses.add(res);

    const isMock = isUsingMockTemporal();
    let isClosed = false;

    const sendSSE = (event: string, data: any) => {
      ChatService.recordEvent(jobId, event, data);
    };

    // 15 秒心跳保活
    const heartbeatTimer = setInterval(() => {
      if (isClosed) return;
      try {
        res.write(`event: heartbeat\ndata: ${JSON.stringify({ timestamp: Date.now() })}\n\n`);
      } catch {
        // ignore
      }
    }, 15000);

    const cleanup = () => {
      if (isClosed) return;
      isClosed = true;
      clearInterval(heartbeatTimer);
      jobBuffer.activeResponses.delete(res);
      res.end();
    };

    res.on('close', cleanup);

    // 监听完成事件触发优雅关闭
    const onResult = (data: any) => {
      if (data.jobId === jobId && !isClosed) {
        setTimeout(cleanup, 200);
      }
    };

    agentEventEmitter.on('result', onResult);
    res.on('close', () => {
      agentEventEmitter.off('result', onResult);
    });

    if (!isMock) {
      // Temporal 轮询模式
      (async () => {
        try {
          const client = await getTemporalClient();
          const handle = client.workflow.getHandle(jobId);
          let lastPlanIndex = 0;
          let lastStatus = '';

          while (!isClosed) {
            try {
              const status = (await handle.query(currentStatusQuery)) as string;
              if (status && status !== lastStatus) {
                lastStatus = status;
                sendSSE('status', { status });
              }

              const plan = (await handle.query(currentPlanQuery)) as any;
              if (plan && plan.steps && plan.steps.length > lastPlanIndex) {
                for (let i = lastPlanIndex; i < plan.steps.length; i++) {
                  sendSSE('thought', { step: plan.steps[i], stepIndex: i });
                }
                lastPlanIndex = plan.steps.length;
              }

              const desc = await handle.describe();
              if (desc.status.name === 'COMPLETED') {
                const result = await handle.result();
                sendSSE('result', result);
                break;
              }
              if (desc.status.name === 'FAILED' || desc.status.name === 'TERMINATED') {
                sendSSE('error', { message: `Workflow ${desc.status.name}` });
                break;
              }
            } catch {
              // 稍后重试轮询
            }
            await new Promise((r) => setTimeout(r, 600));
          }
          cleanup();
        } catch (err: any) {
          sendSSE('error', {
            message: err?.message || 'Workflow connection error',
          });
          cleanup();
        }
      })();
    }
  }

  /**
   * 获取用户订单历史
   */
  async getUserOrders(userId: string, businessId: string) {
    const pool = getPgPool();
    const query = `
      SELECT
        o.order_id,
        o.status,
        o.carrier,
        o.tracking_number,
        o.estimated_delivery,
        o.total_amount,
        o.created_at,
        ua.recipient_name,
        ua.phone,
        ua.full_address
      FROM orders o
      LEFT JOIN user_addresses ua ON o.address_id = ua.id
      WHERE o.business_id = $1 AND (o.user_id = $2 OR $2 = 'all')
      ORDER BY o.created_at DESC
      LIMIT 20
    `;
    const res = await pool.query(query, [businessId.toLowerCase().trim(), userId]);
    return res.rows;
  }
}

// 注册全局事件监听器，实现 Job 级别的全生命周期事件录入与多客户端广播
if (!(globalThis as any).__chatServiceEmitterAttached) {
  (globalThis as any).__chatServiceEmitterAttached = true;
  agentEventEmitter.on('thought', (data: any) => {
    if (data?.jobId) ChatService.recordEvent(data.jobId, 'thought', data);
  });
  agentEventEmitter.on('tool', (data: any) => {
    if (data?.jobId) ChatService.recordEvent(data.jobId, 'tool', data);
  });
  agentEventEmitter.on('approval_required', (data: any) => {
    if (data?.jobId) ChatService.recordEvent(data.jobId, 'approval_required', data);
  });
  agentEventEmitter.on('result', (data: any) => {
    if (data?.jobId) {
      if (data.cards && Array.isArray(data.cards) && data.cards.length > 0) {
        ChatService.recordEvent(data.jobId, 'cards', { cards: data.cards });
      }
      ChatService.recordEvent(data.jobId, 'result', data);
    }
  });
}
