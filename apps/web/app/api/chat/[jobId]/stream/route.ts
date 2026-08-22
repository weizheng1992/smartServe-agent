import { type NextRequest, NextResponse } from "next/server";
import { ChatSessionOrchestrator } from "../../services/chatSessionOrchestrator";

export const dynamic = "force-dynamic";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;

  try {
    const headers = {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    };

    const stream = ChatSessionOrchestrator.createEventStream({
      jobId,
      signal: req.signal,
    });

    return new NextResponse(stream, { headers });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error in stream route:", error);
    return NextResponse.json(
      { error: errMsg || "Stream processing error" },
      { status: 500 },
    );
  }
}
