import { WorkflowOrchestrator, agentEventEmitter } from 'engine';
import { type NextRequest, NextResponse } from 'next/server';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const effectiveMessage = (body.message || body.input || '').trim();
    if (!effectiveMessage) {
      return NextResponse.json({ success: false, error: '消息内容不能为空' }, { status: 400 });
    }

    const businessId = body.businessId || 'aurora';
    const userId = body.userId || 'CUST-8801';
    const threadId = body.threadId || `merchant_thread_${userId}_${businessId}`;
    const jobId = `job_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;

    // 统一交由 WorkflowOrchestrator 与引擎内核负责会话流转与消息物理落库 (避免重复插入双重消息)
    const dispatchRes = await WorkflowOrchestrator.dispatchJob({
      jobId,
      threadId,
      userId,
      message: effectiveMessage,
      businessId,
    });

    // 等待同步返回结果
    const finalState: any = await dispatchRes.promise;
    const output = finalState?.output || finalState?.result || '极光潮品智能客服已为您处理完毕。';
    const messageId = `ast_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;

    // 触发 SSE 实时推送
    agentEventEmitter.emit(`thread:${threadId}:message`, {
      id: messageId,
      role: 'assistant',
      content: output,
      cards: finalState?.cards || [],
      timestamp: new Date().toISOString(),
    });

    return NextResponse.json({
      success: true,
      messageId,
      jobId,
      threadId,
      userId,
      output,
      result: output,
      cards: finalState?.cards || [],
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
