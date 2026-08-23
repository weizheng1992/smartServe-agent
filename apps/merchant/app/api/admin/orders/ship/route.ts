import { MerchantDomainService } from '@/src/services/merchantDomainService';
import { type NextRequest, NextResponse } from 'next/server';

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    if (!body.orderId || !body.trackingNo) {
      return NextResponse.json({ success: false, message: 'orderId and trackingNo are required' }, { status: 400 });
    }

    const result = await MerchantDomainService.shipOrder({
      orderId: body.orderId,
      carrierCode: body.carrierCode || 'SF',
      trackingNo: body.trackingNo,
    });

    return NextResponse.json(result);
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, message: errMsg }, { status: 500 });
  }
}
