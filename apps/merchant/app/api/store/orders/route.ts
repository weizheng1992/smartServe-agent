import { MerchantDomainService } from '@/src/services/merchantDomainService';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const userId = searchParams.get('userId') || 'CUST-8801';
    const orders = await MerchantDomainService.listOrders({
      userId,
      limit: 20,
    });
    return NextResponse.json({ success: true, orders });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const result = await MerchantDomainService.placeOrder({
      customerId: body.customerId || 'CUST-8801',
      skuCode: body.skuCode,
      quantity: body.quantity || 1,
      shippingAddress: body.shippingAddress || '北京市海淀区中关村南大街1号院8号楼1201室',
      recipientName: body.recipientName || '张伟',
      recipientPhone: body.recipientPhone || '13800138000',
    });

    return NextResponse.json(result);
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
