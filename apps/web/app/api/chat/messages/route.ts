import { db } from 'db';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const threadId = searchParams.get('threadId') || 'default_thread';

    console.log(`[API /api/messages] Fetching physical chat history for thread: ${threadId}`);
    const messages = await db.getMessages(threadId);

    return NextResponse.json({
      success: true,
      messages: messages.map((m) => ({
        role: m.role,
        content: m.content,
        timestamp: m.timestamp,
      })),
    });
  } catch (error: any) {
    console.error('Error fetching chat history:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
