import { BadRequestException, Injectable } from '@nestjs/common';
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

export interface DispatchChatDto {
  message?: string;
  input?: string;
  threadId?: string;
  userId?: string;
  businessId?: string;
  imageUrls?: string[];
  sync?: boolean;
}

@Injectable()
export class ChatService {
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
   * 管道化处理 SSE 实时推流
   */
  pipeSSE(jobId: string, res: Response) {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache, no-transform');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.flushHeaders?.();

    const sendSSE = (event: string, data: any) => {
      try {
        res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
      } catch (err) {
        logger.warn({ err, jobId }, '[ChatService] SSE write error');
      }
    };

    const isMock = isUsingMockTemporal();
    let isClosed = false;

    // 15 秒心跳保活
    const heartbeatTimer = setInterval(() => {
      if (isClosed) return;
      sendSSE('heartbeat', { timestamp: Date.now() });
    }, 15000);

    const cleanup = () => {
      if (isClosed) return;
      isClosed = true;
      clearInterval(heartbeatTimer);
      res.end();
    };

    res.on('close', cleanup);

    if (isMock) {
      const onThought = (data: any) => {
        if (data.jobId === jobId && !isClosed) sendSSE('thought', data);
      };
      const onTool = (data: any) => {
        if (data.jobId === jobId && !isClosed) sendSSE('tool', data);
      };
      const onApproval = (data: any) => {
        if (data.jobId === jobId && !isClosed) sendSSE('approval_required', data);
      };
      const onResult = (data: any) => {
        if (data.jobId === jobId && !isClosed) {
          if (data.cards && Array.isArray(data.cards) && data.cards.length > 0) {
            sendSSE('cards', { cards: data.cards });
          }
          sendSSE('result', data);
          setTimeout(cleanup, 200);
        }
      };

      agentEventEmitter.on('thought', onThought);
      agentEventEmitter.on('tool', onTool);
      agentEventEmitter.on('approval_required', onApproval);
      agentEventEmitter.on('result', onResult);

      const origCleanup = cleanup;
      res.on('close', () => {
        agentEventEmitter.off('thought', onThought);
        agentEventEmitter.off('tool', onTool);
        agentEventEmitter.off('approval_required', onApproval);
        agentEventEmitter.off('result', onResult);
        origCleanup();
      });
    } else {
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
