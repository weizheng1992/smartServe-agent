import { MerchantDomainService } from '@/src/services/merchantDomainService';
import { verifySpiRequest } from '@/src/services/spiAuthGuard';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest) {
  try {
    const auth = await verifySpiRequest(req, '', { requireSignature: false });
    if (!auth.isValid) {
      return NextResponse.json({ success: false, message: auth.error }, { status: 401 });
    }

    const { searchParams } = new URL(req.url);
    const userId = searchParams.get('userId') || undefined;
    const status = searchParams.get('status') || undefined;
    const limit = searchParams.get('limit') ? Number.parseInt(searchParams.get('limit')!, 10) : 10;

    const orders = await MerchantDomainService.listOrders({
      userId,
      status,
      limit,
    });
    return NextResponse.json({
      success: true,
      data: orders,
      timestamp: Date.now(),
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error('[SPI] GET /spi/v1/orders/list failed:', err);
    return NextResponse.json({ success: false, message: errMsg }, { status: 500 });
  }
}
