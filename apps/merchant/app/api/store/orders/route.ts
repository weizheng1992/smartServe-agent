import { MerchantDomainService } from '@/src/services/merchantDomainService';
import { type NextRequest, NextResponse } from 'next/server';

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const userId = searchParams.get('userId') || 'CUST-8801';
    const status = searchParams.get('status') || undefined;
    const orders = await MerchantDomainService.listOrders({
      userId,
      status: status && status !== 'ALL' ? status : undefined,
      limit: 50,
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
    const customerId = body.customerId || 'CUST-8801';

    // 1. 如果是购物车多 SKU 批量下单
    if (Array.isArray(body.items) && body.items.length > 0) {
      const fullAddress =
        typeof body.shippingAddress === 'string'
          ? body.shippingAddress
          : body.shippingAddress?.fullAddress || '北京市海淀区中关村南大街1号院8号楼1201室';

      const result = await MerchantDomainService.createOrderFromCart({
        customerId,
        items: body.items,
        shippingAddress: {
          recipientName:
            (typeof body.shippingAddress === 'object' ? body.shippingAddress?.recipientName : undefined) ||
            body.recipientName ||
            '张伟',
          phone:
            (typeof body.shippingAddress === 'object' ? body.shippingAddress?.phone : undefined) ||
            body.recipientPhone ||
            '13800138000',
          fullAddress,
        },
      });

      return NextResponse.json(result);
    }

    // 2. 单商品直接购买
    const result = await MerchantDomainService.placeOrder({
      customerId,
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
