import { type NextRequest, NextResponse } from 'next/server';
import { ChatSessionOrchestrator } from '../../services/chatSessionOrchestrator';

export const dynamic = 'force-dynamic';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Requested-With',
};

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: CORS_HEADERS,
  });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;

  try {
    const headers = {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      ...CORS_HEADERS,
    };

    const stream = ChatSessionOrchestrator.createEventStream({
      jobId,
      signal: req.signal,
    });

    return new NextResponse(stream, { headers });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error('Error in stream route:', error);
    return NextResponse.json({ error: errMsg || 'Stream processing error' }, { status: 500, headers: CORS_HEADERS });
  }
}
