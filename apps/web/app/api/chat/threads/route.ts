import { db } from 'db';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const userId = searchParams.get('userId');

    if (!userId) {
      return NextResponse.json({ success: false, error: 'userId is required' }, { status: 400 });
    }

    const threads = await db.getUserThreads(userId);
    return NextResponse.json({ success: true, threads });
  } catch (err: any) {
    console.error('[API Get Threads Error]:', err);
    return NextResponse.json({ success: false, error: err.message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const { userId, threadId } = await req.json();

    if (!userId || !threadId) {
      return NextResponse.json({ success: false, error: 'userId and threadId are required' }, { status: 400 });
    }

    const thread = await db.createThread(threadId, userId);
    return NextResponse.json({ success: true, thread });
  } catch (err: any) {
    console.error('[API Create Thread Error]:', err);
    return NextResponse.json({ success: false, error: err.message }, { status: 500 });
  }
}
