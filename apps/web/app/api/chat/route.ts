import { type NextRequest, NextResponse } from 'next/server';
import { ChatSessionService } from './services/chatSessionService';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
  'Access-Control-Allow-Headers':
    'Content-Type, Authorization, X-Requested-With, X-Tenant-Id, X-Signature, X-Timestamp, X-Nonce',
  'Access-Control-Max-Age': '86400',
};

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: CORS_HEADERS,
  });
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { message, threadId, userId, businessId, imageUrls, input, sync } = body;

    const result = await ChatSessionService.dispatchChatRequest({
      message: message || input,
      input: input || message,
      threadId,
      userId,
      businessId,
      imageUrls,
      sync,
      req,
    });

    if (result.error) {
      return NextResponse.json({ error: result.error }, { status: result.statusCode || 500, headers: CORS_HEADERS });
    }

    return NextResponse.json(result, { headers: CORS_HEADERS });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error('Error in POST /api/chat endpoint:', error);
    return NextResponse.json({ error: errMsg || 'Internal Server Error' }, { status: 500, headers: CORS_HEADERS });
  }
}
