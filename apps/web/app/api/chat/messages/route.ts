import { db, getDrizzle, threads } from "db";
import { eq } from "drizzle-orm";
import { sanitizeTenantResponse } from "engine";
import { type NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const threadId = searchParams.get("threadId") || "default_thread";

    console.log(
      `[API /api/messages] Fetching physical chat history for thread: ${threadId}`,
    );
    const messages = await db.getMessages(threadId);

    // Resolve thread's tenant identity
    let businessId = "ecommerce";
    try {
      const drizzle = getDrizzle();
      if (drizzle) {
        const threadRows = await drizzle
          .select()
          .from(threads)
          .where(eq(threads.id, threadId))
          .limit(1);
        if (threadRows[0]?.businessId) {
          businessId = threadRows[0].businessId;
        }
      }
    } catch (tErr) {
      console.warn(
        "[API /api/messages] Failed to resolve thread businessId:",
        tErr,
      );
    }

    return NextResponse.json({
      success: true,
      messages: messages.map((m) => ({
        id: m.id,
        role: m.role,
        content:
          m.role === "assistant"
            ? sanitizeTenantResponse(m.content, businessId)
            : m.content,
        timestamp: m.timestamp,
      })),
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error fetching chat history:", error);
    return NextResponse.json(
      { success: false, error: errMsg },
      { status: 500 },
    );
  }
}
