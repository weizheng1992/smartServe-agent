import { ApprovalGatekeeper } from 'engine';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const tenantId = searchParams.get('tenantId') || 'aurora';
    const status = searchParams.get('status') || undefined;

    const merchantApprovals = await ApprovalGatekeeper.listPendingApprovals({
      tenantId: tenantId === 'all' ? undefined : tenantId,
      status: status === 'all' ? undefined : status,
    });

    return NextResponse.json({
      success: true,
      approvals: merchantApprovals,
      total: merchantApprovals.length,
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { approvalId, threadId, action, rejectionReason, humanReply, replyMessage, isFinish } = body;

    const result = await ApprovalGatekeeper.processApprovalAction({
      approvalId,
      threadId,
      action,
      rejectionReason,
      humanReply: humanReply || replyMessage,
      isFinish,
    });

    if (result.error) {
      return NextResponse.json({ success: false, error: result.error }, { status: result.statusCode || 400 });
    }

    return NextResponse.json({
      success: true,
      ...result,
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
