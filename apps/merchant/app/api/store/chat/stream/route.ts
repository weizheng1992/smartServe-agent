import { agentEventEmitter } from 'engine';
import { type NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const threadId = searchParams.get('threadId');

  if (!threadId) {
    return new Response('Missing threadId parameter', { status: 400 });
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      const sendEvent = (event: string, data: any) => {
        try {
          controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
        } catch {
          // Stream already closed or errored
        }
      };

      // 发送连接建立就绪事件
      sendEvent('connected', { threadId, timestamp: Date.now() });

      // 订阅当前会话的实时消息事件 (人工客服协同接管、系统通知等)
      const onThreadMessage = (data: any) => {
        sendEvent('message', data);
      };

      const threadChannel = `thread:${threadId}:message`;
      agentEventEmitter.on(threadChannel, onThreadMessage);

      // 15 秒心跳保活
      const heartbeatTimer = setInterval(() => {
        sendEvent('heartbeat', { timestamp: Date.now() });
      }, 15000);

      req.signal.addEventListener('abort', () => {
        clearInterval(heartbeatTimer);
        agentEventEmitter.off(threadChannel, onThreadMessage);
        try {
          controller.close();
        } catch {
          // ignore
        }
      });
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
