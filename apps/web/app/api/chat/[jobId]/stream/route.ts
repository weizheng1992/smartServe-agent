import { agentEventEmitter, getTemporalClient, isUsingMockTemporal } from 'engine';
import { type NextRequest, NextResponse } from 'next/server';

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
        const sendSSE = (event: string, data: any) => {
          try {
            controller.enqueue(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
          } catch (e) {
            // Controller might be closed
          }
        };

        if (!isMock) {
          // Real Temporal connection Mode
          try {
            sendSSE('status', { status: 'running', message: 'Workflow picked up by Temporal' });
            const client = await getTemporalClient();
            const handle = client.workflow.getHandle(jobId);
            const result = await handle.result();
            sendSSE('result', result);
            controller.close();
          } catch (err) {
            console.error('[Temporal SSE] failed:', err);
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
  } catch (error: any) {
    console.error('Error in stream route:', error);
    return NextResponse.json({ error: error.message || 'Stream processing error' }, { status: 500 });
  }
}
