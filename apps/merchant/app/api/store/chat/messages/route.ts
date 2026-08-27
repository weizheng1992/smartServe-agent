import { ConversationRepository, getPgPool } from "db";
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

    const pool = getPgPool();
    let pgUserId: string | null = null;
    if (userId) {
      try {
        const userRes = await pool.query(
          "SELECT id FROM users WHERE LOWER(email) = LOWER($1) OR id = $2 LIMIT 1",
          [`${userId}@example.com`, userId],
        );
        if (userRes.rows?.[0]) {
          pgUserId = userRes.rows[0].id;
        }
      } catch {
        // ignore
      }
    }

    // 查询该租户下的最近会话列表 (直接在数据库层过滤当前用户)
    const listRes = await ConversationRepository.listConversations({
      businessId: tenantId,
      userId: userId || undefined,
      limit: 50,
      offset: 0,
    });

    // 过滤出属于当前用户的全部历史会话
    const userThreads = listRes.items.filter((item) => {
      if (!userId) return false;
      return (
        item.userId === userId ||
        (pgUserId && item.userId === pgUserId) ||
        item.threadId.includes(`_${userId}_`) ||
        item.threadId.includes(`_${userId}`) ||
        item.threadId.startsWith(userId)
      );
    });

    // 如果前端未指定 threadId，且当前用户有历史会话，则自动定位到该用户最近的会话
    if (!threadId && userThreads.length > 0) {
      const activeThreadWithMsgs = userThreads.find((t) =>
        Boolean(t.lastMessageSnippet),
      );
      threadId = activeThreadWithMsgs?.threadId || userThreads[0].threadId;
    }

    if (!threadId) {
      return NextResponse.json({
        success: true,
        threadId: null,
        thread: null,
        messages: [],
        userThreads,
      });
    }

    const timeline = await ConversationRepository.getConversationTimeline(
      threadId,
      tenantId,
    );

    const includeOlder =
      searchParams.get("includeOlder") === "true" ||
      searchParams.get("allHistory") === "true";

    let allHistoricalMessages: any[] | undefined = undefined;
    if (includeOlder && userThreads.length > 0) {
      const allMsgs: any[] = [];
      for (const t of userThreads) {
        const tl = await ConversationRepository.getConversationTimeline(
          t.threadId,
          tenantId,
        );
        if (tl?.messages && tl.messages.length > 0) {
          allMsgs.push(
            ...tl.messages.map((m: any) => ({
              ...m,
              threadId: t.threadId,
            })),
          );
        }
      }
      // 按时间正序排列全部历史消息
      allMsgs.sort(
        (a, b) =>
          new Date(a.createdAt || a.timestamp || 0).getTime() -
          new Date(b.createdAt || b.timestamp || 0).getTime(),
      );
      allHistoricalMessages = allMsgs;
    }

    return NextResponse.json({
      success: true,
      threadId,
      thread: timeline?.thread || null,
      messages: timeline?.messages || [],
      userThreads,
      allHistoricalMessages,
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { success: false, error: errMsg },
      { status: 500 },
    );
  }
}
