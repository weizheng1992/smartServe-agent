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
    const userEmail = searchParams.get('userEmail') || undefined;

    const user = await MerchantDomainService.getUserInfo({ userId, userEmail });
    return NextResponse.json({
      success: true,
      data: user,
      timestamp: Date.now(),
    });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error('[SPI] GET /spi/v1/user/info failed:', err);
    return NextResponse.json({ success: false, message: errMsg }, { status: 500 });
  }
}
