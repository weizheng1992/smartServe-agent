import { type NextRequest, NextResponse } from "next/server";
import { ChatSessionService } from "./services/chatSessionService";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { message, threadId, userId, businessId, imageUrls } = body;

    const result = await ChatSessionService.dispatchChatRequest({
      message,
      threadId,
      userId,
      businessId,
      imageUrls,
      req,
    });

    if (result.error) {
      return NextResponse.json(
        { error: result.error },
        { status: result.statusCode || 500 },
      );
    }

    return NextResponse.json(result);
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error in POST /api/chat endpoint:", error);
    return NextResponse.json(
      { error: errMsg || "Internal Server Error" },
      { status: 500 },
    );
  }
}
