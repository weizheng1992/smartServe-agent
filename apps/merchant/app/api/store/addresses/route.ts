import { MerchantDomainService } from '@/src/services/merchantDomainService';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const userId = searchParams.get('userId') || 'CUST-8801';
    const addresses = await MerchantDomainService.getCustomerAddresses(userId);
    return NextResponse.json({ success: true, addresses });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const userId = body.userId || 'CUST-8801';

    if (!body.recipientName || !body.phone) {
      return NextResponse.json({ success: false, error: '收货人姓名和手机号为必填项' }, { status: 400 });
    }

    const result = await MerchantDomainService.saveCustomerAddress(userId, {
      id: body.id,
      recipientName: body.recipientName,
      phone: body.phone,
      province: body.province,
      city: body.city,
      district: body.district,
      detailAddress: body.detailAddress,
      fullAddress: body.fullAddress,
      isDefault: body.isDefault,
    });

    return NextResponse.json(result);
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
