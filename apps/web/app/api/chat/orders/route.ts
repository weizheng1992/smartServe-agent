import { type NextRequest, NextResponse } from "next/server";
import { OrderDomainService } from "tools";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const userId = searchParams.get("userId") || undefined;
    const userEmail = searchParams.get("userEmail") || undefined;
    const threadId = searchParams.get("threadId") || undefined;
    const businessId = searchParams.get("businessId") || undefined;

    const orders = await OrderDomainService.getUserOrdersDetailed({
      userId,
      userEmail,
      threadId,
      businessId,
    });

    return NextResponse.json({
      success: true,
      orders,
    });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("[GET /api/chat/orders] Failed:", error);
    return NextResponse.json(
      { success: false, error: errMsg || "Failed to fetch user orders" },
      { status: 500 },
    );
  }
}
