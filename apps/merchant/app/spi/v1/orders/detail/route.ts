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
    const orderId = searchParams.get('orderId');
    if (!orderId) {
      return NextResponse.json({ success: false, message: 'orderId is required' }, { status: 400 });
    }

    const order = await MerchantDomainService.getOrderDetail(orderId);
    if (!order) {
      return NextResponse.json({ success: false, message: `Order ${orderId} not found` }, { status: 404 });
    }

    return NextResponse.json({
      success: true,
      data: order,
      timestamp: Date.now(),
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error('[SPI] GET /spi/v1/orders/detail failed:', err);
    return NextResponse.json({ success: false, message: errMsg }, { status: 500 });
  }
}
