import {
  agentEventEmitter,
  currentPlanQuery,
  currentStatusQuery,
  getTemporalClient,
  isUsingMockTemporal,
} from 'engine';
import { type NextRequest, NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;

  try {
    const isMock = isUsingMockTemporal();

    // Set headers for Server-Sent Events (SSE)
    const headers = {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
    };

    const stream = new ReadableStream({
      async start(controller) {
        const sendSSE = (event: string, data: unknown) => {
          try {
            controller.enqueue(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
          } catch (e) {
            // Controller might be closed
          }
        };

        if (!isMock) {
          // Real Temporal connection Mode with live status polling
          let pollInterval: NodeJS.Timeout | null = null;
          let lastStatus = '';
          try {
            sendSSE('status', {
              status: 'running',
              message: 'Temporal 工作流引擎已接管调度，正在初始化...',
            });
            const client = await getTemporalClient();
            const handle = client.workflow.getHandle(jobId);

            // 周期性 Query 物理 Temporal 工作流状态并实时通过 SSE 推送给前端
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
        // 延迟执行订阅和回放，给 Next.js/Browser 足够的时间建立物理 SSE 握手连接，
        // 彻底解决同步快速失败/瞬间完成的任务导致浏览器未注册事件即关闭从而无限 loading 的致命 Bug！
        let unsubscribe = () => {};

        const subscriptionTimeout = setTimeout(() => {
          unsubscribe = agentEventEmitter.playbackAndSubscribe(
            jobId,
            (statusData) => {
              sendSSE('status', statusData);
            },
            (resultData) => {
              sendSSE('result', resultData);
              // Cleanup memory journal & socket
              unsubscribe();
              agentEventEmitter.clearJob(jobId);
              try {
                controller.close();
              } catch (e) {}
            },
          );
        }, 150);

        // Connection heartbeat timer to prevent serverless function premature timeouts
        const heartbeat = setInterval(() => {
          try {
            controller.enqueue(': heartbeat\n\n');
          } catch (e) {
            clearInterval(heartbeat);
          }
        }, 15000);

        // Clean up on disconnect
        req.signal.addEventListener('abort', () => {
          clearTimeout(subscriptionTimeout);
          clearInterval(heartbeat);
          unsubscribe();
        });
      },
    });

    return new NextResponse(stream, { headers });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error('Error in stream route:', error);
    return NextResponse.json({ error: errMsg || 'Stream processing error' }, { status: 500 });
  }
}
