import { ConversationRepository } from "db";
import { type NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const tenantId =
      searchParams.get("businessId") ||
      searchParams.get("tenantId") ||
      "aurora";
    let threadId = searchParams.get("threadId");
    const userId = searchParams.get("userId");

    // 如果未传 threadId，但传了 userId，则尝试找到该用户最近活跃的会话
    if (!threadId && userId) {
      const listRes = await ConversationRepository.listConversations({
        businessId: tenantId,
        limit: 10,
        offset: 0,
      });
      const userThread = listRes.items.find((item) => item.userId === userId);
      if (userThread) {
        threadId = userThread.threadId;
      }
    }

    if (!threadId) {
      return NextResponse.json({
        success: true,
        threadId: null,
        thread: null,
        messages: [],
      });
    }

    const timeline = await ConversationRepository.getConversationTimeline(
      threadId,
      tenantId,
    );

    return NextResponse.json({
      success: true,
      threadId,
      thread: timeline?.thread || null,
      messages: timeline?.messages || [],
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { success: false, error: errMsg },
      { status: 500 },
    );
  }
}
