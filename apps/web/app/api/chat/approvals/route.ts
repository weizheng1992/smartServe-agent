import { type NextRequest, NextResponse } from "next/server";
import { ApprovalService } from "../services/approvalService";

export async function GET(_req: NextRequest) {
  try {
    const list = await ApprovalService.listPendingApprovals();
    return NextResponse.json({ success: true, approvals: list });
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error fetching approvals:", error);
    return NextResponse.json(
      { error: errMsg || "Internal Server Error" },
      { status: 500 },
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const result = await ApprovalService.processApprovalAction(body);

    if (result.error) {
      return NextResponse.json(
        { error: result.error },
        { status: result.statusCode || 500 },
      );
    }

    return NextResponse.json(result);
  } catch (error: unknown) {
    const errMsg = error instanceof Error ? error.message : String(error);
    console.error("Error handling approval action:", error);
    return NextResponse.json(
      { error: errMsg || "Internal Server Error" },
      { status: 500 },
    );
  }
}
