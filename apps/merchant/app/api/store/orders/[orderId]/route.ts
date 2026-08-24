import { MerchantDomainService } from '@/src/services/merchantDomainService';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest, props: { params: Promise<{ orderId: string }> }) {
  try {
    const { orderId } = await props.params;
    if (!orderId) {
      return NextResponse.json({ success: false, error: '缺少 orderId 参数' }, { status: 400 });
    }

    const order = await MerchantDomainService.getOrderDetail(orderId);
    if (!order) {
      return NextResponse.json({ success: false, error: `订单 [${orderId}] 不存在` }, { status: 404 });
    }

    return NextResponse.json({ success: true, order });
  } catch (err: unknown) {
    const errMsg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ success: false, error: errMsg }, { status: 500 });
  }
}
