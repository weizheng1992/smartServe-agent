import { ConversationRepository } from 'db';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const tenantId = searchParams.get('tenantId') || 'aurora';
    const status = searchParams.get('status') || undefined;
    const searchKeyword = searchParams.get('search') || undefined;

    const res = await ConversationRepository.listConversations({
      businessId: tenantId,
      status: status === 'all' ? undefined : status,
      searchKeyword,
      limit: 50,
      offset: 0,
    });

    const conversations = (res.items || []).map((item) => ({
      ...item,
      id: item.threadId,
      lastMessage: item.lastMessageSnippet,
    }));

    return NextResponse.json({
      success: true,
      tenantId,
      conversations,
      total: res.total,
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
