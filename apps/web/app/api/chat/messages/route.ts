import { db } from "db";
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

    // Resolve thread's tenant identity via DB encapsulation
    let businessId: string | undefined;
    try {
      const thread = await db.getThread(threadId);
      if (thread?.businessId) {
        businessId = thread.businessId;
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
          m.role === "assistant" && businessId
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
