import { MerchantDomainService } from '@/src/services/merchantDomainService';
import { verifySpiRequest } from '@/src/services/spiAuthGuard';
import { type NextRequest, NextResponse } from 'next/server';
import type { ThirdPartyOrderActionRequest } from 'types';

export async function POST(req: NextRequest) {
  try {
    const rawBody = await req.text();
    const signature = req.headers.get('x-signature') || '';

    const auth = await verifySpiRequest(req, rawBody);
    if (!auth.isValid) {
      return NextResponse.json({ success: false, message: auth.error }, { status: 401 });
    }

    const payload = JSON.parse(rawBody) as ThirdPartyOrderActionRequest;
    if (!payload.orderId || !payload.actionType) {
      return NextResponse.json({ success: false, message: 'orderId and actionType are required' }, { status: 400 });
    }

    const result = await MerchantDomainService.executeOrderAction(payload, signature);
    return NextResponse.json({
      success: result.success,
      data: result,
      timestamp: Date.now(),
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error('[SPI] POST /spi/v1/orders/action failed:', err);
    return NextResponse.json({ success: false, message: errMsg }, { status: 500 });
  }
}
