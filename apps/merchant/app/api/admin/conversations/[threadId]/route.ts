import { ConversationRepository } from 'db';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest, { params }: { params: Promise<{ threadId: string }> }) {
  try {
    const { threadId } = await params;
    const { searchParams } = new URL(req.url);
    const tenantId = searchParams.get('tenantId') || 'aurora';

    const timeline = await ConversationRepository.getConversationTimeline(threadId, tenantId);

    return NextResponse.json({
      success: true,
      data: timeline || {
        thread: {
          threadId,
          businessId: tenantId,
          status: 'active',
          unreadCount: 0,
          tags: [],
          metadata: {},
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        },
        messages: [],
      },
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
